import ast
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docker.errors import ImageNotFound
from requests.exceptions import ReadTimeout

from decode.audit import AuditLayer
from decode.bootstrap.engine import BootstrapEngine
from decode.execution import (
    DockerExecutor,
    EnvironmentCapabilities,
    EnvironmentProvider,
    ExecutionContext,
    ExecutionProvider,
    ExecutionResult,
    FilesystemMode,
    LocalExecutor,
    MCPExecutor,
    ProviderPathMapping,
    ProviderPathStyle,
    SSHExecutor,
    WSLExecutor,
    available_provider_names,
    create_configured_executor,
    create_executor,
)
from decode.execution.base import Command, require_governed_external_io
from decode.governance import GovernanceGate, ScopePolicy
from decode.runtime import ExecutionCoordinator, ExecutionRequest
from decode.skills.base import RiskLevel


def _run_provider(
    executor,
    command,
    timeout=60,
    authorized_executor=None,
    context: ExecutionContext | None = None,
):
    with tempfile.TemporaryDirectory() as directory:
        audit = AuditLayer(Path(directory) / "audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
            audit=audit,
        )
        request = ExecutionRequest(
            action="provider_test",
            risk=RiskLevel.READ,
            command=command,
            executor=authorized_executor or executor.name,
        )

        async def operation():
            return await executor.execute(
                command,
                timeout=timeout,
                context=context,
            )

        return asyncio.run(coordinator.execute(request, operation))


def _run_external_io_guard(
    *,
    authorized_action="domain_io_test",
    authorized_executor="local",
    authorized_target="",
    requested_action="",
    requested_target="",
):
    with tempfile.TemporaryDirectory() as directory:
        audit = AuditLayer(Path(directory) / "audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
            audit=audit,
        )
        request = ExecutionRequest(
            action=authorized_action,
            target=authorized_target,
            risk=RiskLevel.READ,
            executor=authorized_executor,
        )

        async def operation():
            require_governed_external_io(
                action=requested_action,
                target=requested_target,
            )
            return "guarded"

        return asyncio.run(coordinator.execute(request, operation))


class TestExecutionResult(unittest.TestCase):
    def test_summary_success(self):
        r = ExecutionResult(command="echo hi", success=True, stdout="hi\n", exit_code=0)
        self.assertIn("hi", r.summary)

    def test_summary_nonzero_exit(self):
        r = ExecutionResult(command="false", success=False, exit_code=1, stderr="boom")
        self.assertIn("Exit code 1", r.summary)

    def test_summary_error(self):
        r = ExecutionResult(command="nope", success=False, error="Command not found")
        self.assertIn("Error:", r.summary)

    def test_summary_timeout(self):
        r = ExecutionResult(
            command="sleep 99", success=False, timed_out=True, duration=5.0
        )
        self.assertIn("Timed out", r.summary)

    def test_argument_vector_has_a_stable_display_and_versioned_result(self):
        result = ExecutionResult(command=["scanner", "target; harmless"])

        self.assertEqual(result.command, "scanner 'target; harmless'")
        self.assertRegex(result.schema_version, r"^\d+\.\d+\.\d+$")


class _MappedTestProvider(ExecutionProvider):
    def __init__(self, mappings: tuple[ProviderPathMapping, ...]) -> None:
        self._mappings = mappings

    @property
    def name(self) -> str:
        return "mapped/test"

    @property
    def filesystem_mode(self) -> FilesystemMode:
        return FilesystemMode.MAPPED

    @property
    def path_mappings(self) -> tuple[ProviderPathMapping, ...]:
        return self._mappings

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(
            command_execution=True,
            path_mapping=bool(self._mappings),
        )

    async def execute(
        self,
        command: Command,
        timeout: int = 60,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(command=command, provider=self.name, success=True)

    async def check_health(self) -> bool:
        return True


class TestEnvironmentProviderContract(unittest.TestCase):
    def test_execution_context_strictly_validates_environment(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid environment variable"):
            ExecutionContext(environment={"INVALID-NAME": "value"})
        with self.assertRaisesRegex(ValueError, "contains NUL"):
            ExecutionContext(environment={"VALID_NAME": "bad\x00value"})
        with self.assertRaisesRegex(ValueError, "cwd must be an absolute"):
            ExecutionContext(cwd="relative")
        with self.assertRaisesRegex(ValueError, "output paths must be absolute"):
            ExecutionContext(declared_outputs=("relative.txt",))

    def test_all_builtin_executors_expose_typed_identity(self) -> None:
        providers = [
            LocalExecutor(),
            WSLExecutor(distro="kali-linux"),
            DockerExecutor(image="example/image:1"),
            SSHExecutor(host="192.0.2.10"),
            MCPExecutor(server="controlled"),
        ]
        expected_modes = {
            "local": FilesystemMode.SHARED,
            "wsl/kali-linux": FilesystemMode.MAPPED,
            "docker/example/image:1": FilesystemMode.MAPPED,
            "ssh/192.0.2.10:22": FilesystemMode.REMOTE,
            "mcp/controlled": FilesystemMode.NONE,
        }

        for provider in providers:
            with self.subTest(provider=provider.name):
                self.assertIsInstance(provider, EnvironmentProvider)
                identity = provider.identify()
                self.assertEqual(identity.name, provider.name)
                self.assertEqual(identity.kind, provider.name.split("/", 1)[0])
                self.assertEqual(
                    identity.filesystem_mode, expected_modes[provider.name]
                )
                self.assertTrue(identity.capabilities.command_execution)
                self.assertRegex(identity.schema_version, r"^\d+\.\d+\.\d+$")

    def test_builtin_session_support_is_explicit(self) -> None:
        providers = {
            "local": LocalExecutor(),
            "wsl": WSLExecutor(distro="kali-linux"),
            "ssh": SSHExecutor(host="192.0.2.10"),
            "docker": DockerExecutor(image="example/image:1"),
            "mcp": MCPExecutor(server="controlled"),
        }

        self.assertTrue(providers["local"].capabilities.stateful_sessions)
        self.assertTrue(providers["wsl"].capabilities.stateful_sessions)
        self.assertTrue(providers["ssh"].capabilities.stateful_sessions)
        self.assertFalse(providers["docker"].capabilities.stateful_sessions)
        self.assertFalse(providers["mcp"].capabilities.stateful_sessions)

    def test_provider_session_is_bound_to_identity_context_and_close_state(
        self,
    ) -> None:
        provider = WSLExecutor(distro="kali-linux")
        session = provider.open_session(ExecutionContext(cwd="/workspace"))

        self.assertEqual(session.provider, "wsl/kali-linux")
        self.assertEqual(session.context.cwd, "/workspace")
        with self.assertRaisesRegex(ValueError, "does not match"):
            SSHExecutor(host="192.0.2.10").prepare_session_context(session)

        provider.update_session_context(
            session,
            ExecutionContext(cwd="/workspace/sub"),
        )
        summary = provider.close_session(session)

        self.assertEqual(summary["cwd"], "/workspace/sub")
        self.assertTrue(summary["closed"])
        with self.assertRaisesRegex(ValueError, "is closed"):
            provider.prepare_session_context(session)

    def test_provider_session_execution_records_bounded_transcript(self) -> None:
        class SessionProvider(ExecutionProvider):
            @property
            def name(self) -> str:
                return "session/test"

            @property
            def capabilities(self) -> EnvironmentCapabilities:
                return EnvironmentCapabilities(
                    command_execution=True,
                    cwd=True,
                    environment=True,
                    stateful_sessions=True,
                )

            async def execute(
                self,
                command: Command,
                timeout: int = 60,
                env: dict[str, str] | None = None,
                context: ExecutionContext | None = None,
            ) -> ExecutionResult:
                return ExecutionResult(
                    command=command,
                    provider=self.name,
                    success=True,
                    stdout=context.cwd if context is not None else "",
                )

            async def check_health(self) -> bool:
                return True

        provider = SessionProvider()
        session = provider.open_session(ExecutionContext(cwd="/workspace"))
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLayer(Path(directory) / "audit")
            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                audit=audit,
            )
            request = ExecutionRequest(
                action="session_exec",
                risk=RiskLevel.READ,
                command=["pwd"],
                executor=provider.name,
                params={
                    "session_id": session.session_id,
                    "provider_cwd": session.context.cwd,
                },
            )

            async def operation() -> ExecutionResult:
                return await provider.execute_session(session, ["pwd"])

            result = asyncio.run(coordinator.execute(request, operation))
            session.commands_run = session.command_limit
            limited = asyncio.run(coordinator.execute(request, operation))

        self.assertTrue(result.success)
        self.assertEqual(result.value.stdout, "/workspace")
        self.assertFalse(limited.success)
        self.assertIn("reached its command limit", limited.error)
        self.assertEqual(session.commands_run, session.command_limit)
        self.assertEqual(session.transcript[0]["command"], "pwd")

    def test_local_provider_uses_shared_host_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "output.json"
            resolved = LocalExecutor().map_path(candidate, write=True)

        self.assertEqual(resolved.host_path, str(candidate.resolve(strict=False)))
        self.assertEqual(resolved.provider_path, resolved.host_path)
        self.assertTrue(resolved.writable)
        self.assertIsNone(resolved.mapping)

    def test_mapped_provider_uses_longest_authorized_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            provider = _MappedTestProvider(
                (
                    ProviderPathMapping(
                        host_root=str(root),
                        provider_root="/workspace",
                    ),
                    ProviderPathMapping(
                        host_root=str(nested),
                        provider_root="/workspace/nested",
                        writable=True,
                    ),
                )
            )
            resolved = provider.map_path(nested / "result.json", write=True)

        self.assertEqual(resolved.provider_path, "/workspace/nested/result.json")
        self.assertTrue(resolved.writable)
        self.assertEqual(resolved.mapping.provider_root, "/workspace/nested")

    def test_mapped_provider_denies_unmapped_and_read_only_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = _MappedTestProvider(
                (
                    ProviderPathMapping(
                        host_root=str(root),
                        provider_root="C:\\workspace",
                        provider_style=ProviderPathStyle.WINDOWS,
                    ),
                )
            )
            with self.assertRaisesRegex(ValueError, "not writable"):
                provider.map_path(root / "result.json", write=True)
            with self.assertRaisesRegex(ValueError, "no mapping"):
                provider.map_path(root.parent / "outside.json")

    def test_path_mapping_requires_absolute_roots(self) -> None:
        with self.assertRaisesRegex(ValueError, "host_root must be absolute"):
            ProviderPathMapping(host_root="relative", provider_root="/workspace")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "provider_root must be absolute"):
                ProviderPathMapping(
                    host_root=directory,
                    provider_root="relative",
                )

    def test_provider_without_filesystem_contract_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "no filesystem contract"):
            MCPExecutor().map_path("result.json")

    def test_external_providers_without_mappings_fail_closed(self) -> None:
        providers = [
            WSLExecutor(distro="kali-linux"),
            DockerExecutor(image="example/image:1"),
            SSHExecutor(host="192.0.2.10"),
        ]
        for provider in providers:
            with self.subTest(provider=provider.name):
                self.assertFalse(provider.identify().capabilities.path_mapping)
                with self.assertRaisesRegex(ValueError, "no mapping"):
                    provider.map_path("result.json", write=True)

    def test_builtin_mapped_provider_exposes_configured_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mapping = ProviderPathMapping(
                host_root=directory,
                provider_root="/workspace",
                writable=True,
            )
            provider = WSLExecutor(
                distro="kali-linux",
                path_mappings=(mapping,),
            )
            resolved = provider.map_path(Path(directory) / "result.json", write=True)

        self.assertTrue(provider.identify().capabilities.path_mapping)
        self.assertEqual(resolved.provider_path, "/workspace/result.json")

    def test_mcp_rejects_host_execution_context(self) -> None:
        result = _run_provider(
            MCPExecutor(),
            MCPExecutor.encode("probe"),
            context=ExecutionContext(cwd="/workspace"),
        ).value

        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_execution_context")


class TestLocalExecutor(unittest.TestCase):
    def setUp(self):
        self.ex = LocalExecutor()

    def test_echo_runs_and_populates_fields(self):
        r = _run_provider(self.ex, "echo hello").value
        self.assertTrue(r.success)
        self.assertIn("hello", r.stdout)
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(r.command, "echo hello")
        self.assertEqual(r.provider, "local")
        self.assertGreaterEqual(r.duration, 0.0)

    def test_argument_vector_avoids_local_shell_interpretation(self):
        r = _run_provider(
            self.ex,
            [sys.executable, "-c", "import sys; print(sys.argv[1])", "safe; value"],
        ).value

        self.assertTrue(r.success, r.error)
        self.assertEqual(r.stdout.strip(), "safe; value")

    def test_typed_context_applies_cwd_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = ExecutionContext(
                cwd=directory,
                environment={"DECODE_CONTEXT_TEST": "bound"},
            )
            command = [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "print(os.getcwd()); "
                    "print(os.environ['DECODE_CONTEXT_TEST'])"
                ),
            ]
            result = _run_provider(self.ex, command, context=context).value

        lines = result.stdout.splitlines()
        self.assertTrue(result.success, result.error)
        self.assertEqual(Path(lines[0]).resolve(), Path(directory).resolve())
        self.assertEqual(lines[1], "bound")

    def test_context_and_legacy_env_cannot_be_combined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLayer(Path(directory) / "audit")
            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                audit=audit,
            )
            request = ExecutionRequest(
                action="provider_test",
                risk=RiskLevel.READ,
                command=[sys.executable, "-c", "print('blocked')"],
                executor=self.ex.name,
            )

            async def operation():
                return await self.ex.execute(
                    [sys.executable, "-c", "print('blocked')"],
                    env={"ONE": "1"},
                    context=ExecutionContext(environment={"TWO": "2"}),
                )

            result = asyncio.run(coordinator.execute(request, operation)).value

        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_execution_context")

    def test_nonzero_exit_is_not_success(self):
        # `exit 3` is portable across sh and cmd-invoked shells
        r = _run_provider(self.ex, "exit 3").value
        self.assertFalse(r.success)
        self.assertEqual(r.exit_code, 3)

    def test_timeout_is_flagged(self):
        cmd = "ping -n 5 127.0.0.1" if sys.platform == "win32" else "sleep 5"
        r = _run_provider(self.ex, cmd, timeout=1).value
        self.assertTrue(r.timed_out)
        self.assertFalse(r.success)

    def test_health(self):
        self.assertTrue(asyncio.run(self.ex.check_health()))


class TestDockerExecutionContext(unittest.TestCase):
    def test_mapping_becomes_volume_cwd_environment_and_declared_output(self) -> None:
        class FakeContainer:
            def start(self):
                return None

            def wait(self, timeout):
                return {"StatusCode": 0}

            def logs(self, *, stdout, stderr):
                return b"ok\n" if stdout else b""

            def remove(self, *, force):
                return None

        class FakeContainers:
            def __init__(self) -> None:
                self.kwargs = None

            def create(self, image, **kwargs):
                self.kwargs = {"image": image, **kwargs}
                return FakeContainer()

        class FakeClient:
            def __init__(self) -> None:
                self.containers = FakeContainers()

        with tempfile.TemporaryDirectory() as directory:
            mapping = ProviderPathMapping(
                host_root=directory,
                provider_root="/workspace",
                writable=True,
            )
            executor = DockerExecutor(
                image="controlled/image:1",
                path_mappings=(mapping,),
            )
            client = FakeClient()
            executor._client = client
            context = ExecutionContext(
                cwd="/workspace",
                environment={"MODE": "test"},
                declared_outputs=("/workspace/result.json",),
            )
            result = _run_provider(
                executor,
                ["tool", "--output", "/workspace/result.json"],
                context=context,
            ).value

        self.assertTrue(result.success, result.error)
        self.assertEqual(client.containers.kwargs["working_dir"], "/workspace")
        self.assertEqual(client.containers.kwargs["environment"], {"MODE": "test"})
        self.assertEqual(
            client.containers.kwargs["volumes"],
            {directory: {"bind": "/workspace", "mode": "rw"}},
        )

    def test_wait_outcomes_are_classified_without_losing_raw_output(self) -> None:
        class FakeContainer:
            def __init__(self, outcome) -> None:
                self.outcome = outcome
                self.stopped = False
                self.removed = False

            def start(self):
                return None

            def wait(self, timeout):
                if isinstance(self.outcome, Exception):
                    raise self.outcome
                return self.outcome

            def logs(self, *, stdout, stderr):
                return b"partial stdout\n" if stdout else b"partial stderr\n"

            def stop(self, *, timeout):
                self.stopped = True

            def remove(self, *, force):
                self.removed = True

        class FakeClient:
            def __init__(self, container) -> None:
                self.containers = mock.Mock()
                self.containers.create.return_value = container

        outcomes = (
            ("success", {"StatusCode": 0}, True, False, None, 0),
            ("nonzero", {"StatusCode": 7}, False, False, None, 7),
            ("timeout", ReadTimeout("late"), False, True, None, -1),
            (
                "api_error",
                RuntimeError("docker API failed"),
                False,
                False,
                "docker API failed",
                -1,
            ),
            (
                "malformed",
                {"StatusCode": "0"},
                False,
                False,
                "invalid_docker_wait_status",
                -1,
            ),
        )
        for name, outcome, success, timed_out, error, exit_code in outcomes:
            with self.subTest(name=name):
                container = FakeContainer(outcome)
                executor = DockerExecutor(image="controlled/image:1")
                executor._client = FakeClient(container)

                result = _run_provider(executor, ["/bin/echo", "hello"]).value

                self.assertEqual(result.success, success)
                self.assertEqual(result.timed_out, timed_out)
                self.assertEqual(result.error, error)
                self.assertEqual(result.exit_code, exit_code)
                self.assertEqual(container.stopped, timed_out)
                self.assertTrue(container.removed)
                if name != "api_error":
                    self.assertEqual(result.stdout, "partial stdout\n")
                    self.assertEqual(result.stderr, "partial stderr\n")

    def test_missing_sdk_is_reported_without_container_launch(self) -> None:
        executor = DockerExecutor(image="controlled/image:1")
        with mock.patch.object(executor, "_get_client", side_effect=ImportError):
            result = _run_provider(executor, ["/bin/echo", "hello"]).value

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Docker SDK not installed")
        self.assertFalse(result.timed_out)

    def test_start_failure_removes_created_container(self) -> None:
        container = mock.Mock()
        container.start.side_effect = RuntimeError("container start failed")
        client = mock.Mock()
        client.containers.create.return_value = container
        executor = DockerExecutor(image="controlled/image:1")
        executor._client = client

        result = _run_provider(executor, ["/missing-command"]).value

        self.assertFalse(result.success)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.error, "container start failed")
        container.wait.assert_not_called()
        container.remove.assert_called_once_with(force=True)

    def test_missing_image_fails_without_implicit_pull(self) -> None:
        client = mock.Mock()
        client.containers.create.side_effect = ImageNotFound("image absent")
        executor = DockerExecutor(image="controlled/missing:1")
        executor._client = client

        result = _run_provider(executor, ["/bin/echo", "hello"]).value

        self.assertFalse(result.success)
        self.assertEqual(result.error, "docker_image_missing")
        self.assertIn("not cached", result.stderr)
        client.images.pull.assert_not_called()


class TestOptInProviderConformance(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform == "win32" and os.environ.get("DECODE_RUN_WSL_CONFORMANCE") == "1",
        "requires explicit Windows/Kali WSL conformance opt-in",
    )
    def test_kali_wsl_process_outcomes(self) -> None:
        executor = WSLExecutor(distro="kali-linux")
        cases = (
            (["/usr/bin/printf", "decode-wsl-ok"], True, 0),
            (["/usr/bin/false"], False, 1),
            (["decode-absent-tool-59183"], False, None),
        )
        for command, success, exit_code in cases:
            with self.subTest(command=command):
                result = _run_provider(executor, command)
                self.assertEqual(result.value.provider, executor.name)
                self.assertEqual(result.value.success, success)
                if exit_code is not None:
                    self.assertEqual(result.value.exit_code, exit_code)
                else:
                    self.assertNotEqual(result.value.exit_code, 0)
                if success:
                    self.assertEqual(result.value.stdout, "decode-wsl-ok")

    @unittest.skipUnless(
        os.environ.get("DECODE_RUN_DOCKER_CONFORMANCE") == "1",
        "requires explicit offline Docker conformance opt-in",
    )
    def test_docker_existing_image_process_outcomes(self) -> None:
        image = os.environ.get("DECODE_DOCKER_CONFORMANCE_IMAGE", "")
        self.assertTrue(image, "set DECODE_DOCKER_CONFORMANCE_IMAGE")
        executor = DockerExecutor(image=image, network="none")
        client = executor._get_client()
        client.images.get(image)
        images_before = {item.id for item in client.images.list()}
        containers_before = {item.id for item in client.containers.list(all=True)}
        cases = (
            (["/bin/sh", "-c", "printf decode-docker-ok"], True, 0),
            (["/bin/sh", "-c", "exit 7"], False, 7),
            (["/decode-absent-tool-59183"], False, -1),
        )
        for command, success, exit_code in cases:
            with self.subTest(command=command):
                result = _run_provider(executor, command).value
                self.assertEqual(result.provider, executor.name)
                self.assertEqual(result.success, success)
                self.assertEqual(result.exit_code, exit_code)
                if success:
                    self.assertEqual(result.stdout, "decode-docker-ok")
                else:
                    self.assertFalse(result.timed_out)
                if command[0] == "/decode-absent-tool-59183":
                    self.assertTrue(result.error)

        missing_image = DockerExecutor(
            image="decode-conformance-absent-59183:never", network="none"
        )
        missing = _run_provider(missing_image, ["/bin/sh", "-c", "true"]).value
        self.assertEqual(missing.error, "docker_image_missing")
        self.assertEqual({item.id for item in client.images.list()}, images_before)
        self.assertEqual(
            {item.id for item in client.containers.list(all=True)},
            containers_before,
        )


class TestExecutionGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.ex = LocalExecutor()

    def test_direct_execution_is_quarantined_for_every_provider(self):
        providers = [
            LocalExecutor(),
            DockerExecutor(),
            WSLExecutor(),
            SSHExecutor(host="192.0.2.10"),
            MCPExecutor(),
        ]
        for provider in providers:
            with self.subTest(provider=provider.name):
                with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
                    asyncio.run(provider.execute("blocked"))

    def test_executor_context_cannot_switch_provider_family(self):
        result = _run_provider(
            self.ex,
            "echo blocked",
            authorized_executor="docker",
        )
        self.assertFalse(result.success)
        self.assertIn("selected executor", result.error)

    def test_direct_domain_external_io_is_quarantined(self):
        with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
            require_governed_external_io()

    def test_domain_external_io_requires_local_executor_family(self):
        result = _run_external_io_guard(authorized_executor="docker")

        self.assertFalse(result.success)
        self.assertIn("local executor", result.error)

    def test_domain_external_io_action_is_exactly_bound(self):
        result = _run_external_io_guard(
            authorized_action="report_engine",
            requested_action="network_mapper",
        )

        self.assertFalse(result.success)
        self.assertIn("authorized action", result.error)

    def test_domain_external_io_target_is_exactly_bound(self):
        allowed = _run_external_io_guard(
            authorized_target="192.0.2.10",
            requested_target="192.0.2.10",
        )
        denied = _run_external_io_guard(
            authorized_target="192.0.2.10",
            requested_target="192.0.2.11",
        )

        self.assertTrue(allowed.success, allowed.error)
        self.assertEqual(allowed.value, "guarded")
        self.assertFalse(denied.success)
        self.assertIn("authorized target", denied.error)


class TestFactory(unittest.TestCase):
    def test_configured_mapping_binds_only_exact_provider_identity(self):
        with tempfile.TemporaryDirectory() as root:
            configuration = {
                "wsl/kali-linux": [
                    {
                        "host_root": root,
                        "provider_root": "/mnt/work",
                        "writable": True,
                    }
                ],
            }
            with mock.patch.dict(
                "os.environ", {"DECODE_PROVIDER_MAPPINGS": json.dumps(configuration)}
            ):
                selected = create_configured_executor("wsl/kali-linux")
                other = create_configured_executor("wsl/Ubuntu")
            self.assertEqual(
                selected.map_path(root, write=True).provider_path, "/mnt/work"
            )
            with self.assertRaisesRegex(ValueError, "no mapping"):
                other.map_path(root)

    def test_configured_mapping_rejects_bad_or_ambiguous_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            entry = {"host_root": root, "provider_root": "/mnt/work"}
            invalid = [
                "not-json",
                json.dumps({"wsl/kali-linux": [entry, entry]}),
                json.dumps({"wsl/kali-linux": [{**entry, "writable": "maybe"}]}),
                json.dumps({"local": [entry]}),
            ]
            for payload in invalid:
                with (
                    self.subTest(payload=payload),
                    mock.patch.dict(
                        "os.environ", {"DECODE_PROVIDER_MAPPINGS": payload}
                    ),
                ):
                    provider = "local" if '"local"' in payload else "wsl/kali-linux"
                    with self.assertRaisesRegex(
                        ValueError, "Invalid DECODE_PROVIDER_MAPPINGS"
                    ):
                        create_configured_executor(provider)

    def test_configured_mapping_is_read_only_by_default(self):
        with tempfile.TemporaryDirectory() as root:
            payload = json.dumps(
                {"wsl/kali-linux": [{"host_root": root, "provider_root": "/mnt/work"}]}
            )
            with mock.patch.dict("os.environ", {"DECODE_PROVIDER_MAPPINGS": payload}):
                provider = create_configured_executor("wsl/kali-linux")
            with self.assertRaisesRegex(ValueError, "not writable"):
                provider.map_path(root, write=True)

    def test_default_is_local(self):
        self.assertIsInstance(create_executor(), LocalExecutor)

    def test_available_names(self):
        names = available_provider_names()
        self.assertIn("local", names)
        self.assertIn("docker", names)
        self.assertIn("wsl", names)
        # ssh needs a host, so it is not in the zero-arg default set
        self.assertNotIn("ssh", names)

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            create_executor("nonsense")

    def test_ssh_requires_host(self):
        ex = create_executor("ssh", host="example.com", user="root")
        self.assertIn("example.com", ex.name)

    def test_wsl_argument_vector_does_not_use_shell_wrapper(self):
        argv = WSLExecutor(distro="Lab")._wsl_argv(["scanner", "target; harmless"])

        self.assertEqual(
            argv,
            ["wsl.exe", "-d", "Lab", "--", "scanner", "target; harmless"],
        )

    def test_wsl_argument_vector_binds_context_inside_distribution(self):
        context = ExecutionContext(
            cwd="/workspace",
            environment={"MODE": "test value"},
        )
        argv = WSLExecutor(distro="Lab")._wsl_argv(["tool", "arg"], context)

        self.assertEqual(
            argv,
            [
                "wsl.exe",
                "-d",
                "Lab",
                "--cd",
                "/workspace",
                "--",
                "/usr/bin/env",
                "MODE=test value",
                "tool",
                "arg",
            ],
        )

    def test_factory_accepts_qualified_wsl_identity(self):
        self.assertEqual(create_executor("wsl/kali-linux").name, "wsl/kali-linux")
        self.assertEqual(create_executor("wsl:kali-linux").name, "wsl/kali-linux")

    def test_ssh_argument_vector_is_quoted_as_one_remote_command(self):
        argv = SSHExecutor(host="192.0.2.10")._ssh_argv(["scanner", "target; harmless"])

        self.assertEqual(argv[-1], "scanner 'target; harmless'")

    def test_ssh_argument_vector_binds_remote_context(self):
        context = ExecutionContext(
            cwd="/srv/controlled workspace",
            environment={"MODE": "test value"},
        )
        argv = SSHExecutor(host="192.0.2.10")._ssh_argv(["tool", "arg"], context)

        self.assertEqual(
            argv[-1],
            "cd -- '/srv/controlled workspace' && "
            "/usr/bin/env MODE='test value' tool arg",
        )


class TestGracefulUnavailable(unittest.TestCase):
    def test_mcp_without_client_is_not_configured(self):
        r = _run_provider(MCPExecutor(), MCPExecutor.encode("scan", {"t": 1})).value
        self.assertFalse(r.success)
        self.assertEqual(r.error, "mcp_not_configured")
        self.assertFalse(asyncio.run(MCPExecutor().check_health()))

    def test_ssh_without_client_or_host_fails_gracefully(self):
        ex = SSHExecutor(host="203.0.113.255", user="nobody")
        r = _run_provider(ex, "echo hi", timeout=3).value
        self.assertFalse(r.success)


class TestConsequentialMaintenanceBoundaries(unittest.TestCase):
    def test_system_update_is_quarantined_without_external_process(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("decode.bootstrap.engine.subprocess.run") as run,
        ):
            engine = BootstrapEngine(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
                engine.system_update()

        run.assert_not_called()


class TestPublicExecutionBoundaryInventory(unittest.TestCase):
    ENTRY_METHODS = {
        "execute",
        "execute_command",
        "execute_registered_skill",
        "run",
        "system_update",
    }
    EXPLICIT_BOUNDARIES = {
        ("bootstrap/engine.py", "BootstrapEngine", "run"),
        ("bootstrap/engine.py", "BootstrapEngine", "system_update"),
        ("runtime/coordinator.py", "ExecutionCoordinator", "execute"),
        ("skills/registry.py", "SkillRegistry", "execute"),
        ("app/tui/app.py", "AgentREPL", "run"),
        # Host-control surfaces: HostController routes through the coordinator;
        # ToolUseLoop delegates execution to a coordinator-backed invoke; HostSession
        # runs only inside HostAgent's coordinator-governed execute_internal.
        ("runtime/host_controller.py", "HostController", "run"),
        ("runtime/agent_loop.py", "ToolUseLoop", "run"),
        # WorkflowRunner only advances persisted state and calls an injected
        # stage executor; the production adapter is UniversalAgent.run_tool_loop,
        # whose concrete actions all cross ExecutionCoordinator.
        ("workflows/runner.py", "WorkflowRunner", "run"),
        ("hostcontrol/session.py", "HostSession", "run"),
        ("universal_agent.py", "UniversalAgent", "execute_command"),
        (
            "universal_agent.py",
            "UniversalAgent",
            "execute_registered_skill",
        ),
    }

    def test_every_public_execution_entry_point_has_a_known_boundary(self):
        package_root = Path(__file__).parents[1] / "src" / "decode"
        discovered = set()
        unclassified = []

        for path in package_root.rglob("*.py"):
            relative = path.relative_to(package_root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for class_node in (
                node for node in tree.body if isinstance(node, ast.ClassDef)
            ):
                for method in (
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in self.ENTRY_METHODS
                ):
                    entry = (relative, class_node.name, method.name)
                    discovered.add(entry)
                    wrapped_family = (
                        (relative.startswith("skills/") and method.name == "execute")
                        or (
                            relative.startswith("execution/")
                            and method.name == "execute"
                        )
                        or (relative.startswith("agents/") and method.name == "run")
                    )
                    if not wrapped_family and entry not in self.EXPLICIT_BOUNDARIES:
                        unclassified.append(entry)

        self.assertTrue(self.EXPLICIT_BOUNDARIES <= discovered)
        self.assertEqual(unclassified, [])


if __name__ == "__main__":
    unittest.main()
