import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from decode.audit import AuditLayer
from decode.execution import (
    EnvironmentCapabilities,
    ExecutionContext,
    ExecutionProvider,
    ExecutionResult,
    FilesystemMode,
    ProviderPathMapping,
)
from decode.execution.base import Command
from decode.governance import GovernanceGate, ScopePolicy
from decode.hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from decode.hostcontrol import operations as host_ops
from decode.hostcontrol.session import HostSession
from decode.logging_service import LoggingService
from decode.runtime import ExecutionCoordinator, HostController
from decode.runtime.coordinator import ExecutionStatus


def _coordinator(
    tmp: Path,
    mode: PermissionMode = PermissionMode.ASK,
    allow_destructive: bool = False,
):
    audit = AuditLayer(tmp / "audit")
    gate = GovernanceGate(
        ScopePolicy(allow_all=True),
        audit=audit,
        allow_destructive=allow_destructive,
        mode=mode,
    )
    # auto-approve so WRITE proceeds without an interactive prompt
    return ExecutionCoordinator(gate, approval_callback=lambda request: True)


class _MappedSessionProvider(ExecutionProvider):
    def __init__(self, root: Path) -> None:
        self.commands: list[list[str]] = []
        self.contexts: list[ExecutionContext] = []
        self._mappings = (
            ProviderPathMapping(
                host_root=str(root),
                provider_root="/workspace",
                writable=True,
            ),
        )

    @property
    def name(self) -> str:
        return "wsl/kali-linux"

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
            cwd=True,
            environment=True,
            path_mapping=True,
            scoped_filesystem=True,
            stateful_sessions=True,
        )

    async def execute(
        self,
        command: Command,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        command = [str(value) for value in command]
        if command == ["/usr/bin/printenv", "PATH"]:
            return ExecutionResult(
                command=command,
                provider=self.name,
                success=True,
                stdout="/usr/bin\n",
            )
        if command[:1] == ["/usr/bin/find"]:
            return ExecutionResult(
                command=command,
                provider=self.name,
                success=True,
                stdout=(
                    "f\tcurl\t/usr/bin/curl\n"
                    "f\tpwd\t/usr/bin/pwd\n"
                    "f\tsudo\t/usr/bin/sudo\n"
                    "f\ttouch\t/usr/bin/touch\n"
                ),
            )
        if command[:1] == ["/usr/bin/sha256sum"]:
            return ExecutionResult(
                command=command,
                provider=self.name,
                success=True,
                stdout=f"{'c' * 64}  {command[1]}\n",
            )
        if (
            len(command) == 3
            and command[0] == "/usr/bin/test"
            and command[1] in {"-f", "-x"}
        ):
            return ExecutionResult(
                command=command,
                provider=self.name,
                success=True,
            )
        self.commands.append(command)
        self.contexts.append(context or ExecutionContext())
        return ExecutionResult(
            command=command,
            provider=self.name,
            success=True,
            stdout="provider-session",
        )

    async def check_health(self) -> bool:
        return True


class TestHostControlIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "work"
        self.root.mkdir()
        self.scope = FilesystemScope(read_roots=[self.root], write_roots=[self.root])

    def _host(self, mode=PermissionMode.ASK, allow_destructive=False, policy=None):
        coord = _coordinator(
            Path(self.tmp.name), mode=mode, allow_destructive=allow_destructive
        )
        return HostController(
            coord, self.scope, policy if policy is not None else CommandPolicy()
        )

    def _run(self, host, cap, params):
        return asyncio.run(host.run(cap, params))

    def test_read_write_edit_end_to_end(self):
        host = self._host()
        path = str(self.root / "note.txt")
        write = self._run(host, "file_write", {"path": path, "content": "hello world"})
        self.assertEqual(write.status, ExecutionStatus.SUCCESS)
        self.assertTrue(write.value.success)

        read = self._run(host, "file_read", {"path": path})
        self.assertEqual(read.status, ExecutionStatus.SUCCESS)
        self.assertIn("hello world", read.value.normalized["content"])

        edit = self._run(
            host, "file_edit", {"path": path, "old": "world", "new": "there"}
        )
        self.assertEqual(edit.status, ExecutionStatus.SUCCESS)
        self.assertEqual(Path(path).read_text(), "hello there")

    def test_read_outside_scope_is_denied_by_filesystem_scope(self):
        host = self._host()
        outside = str(Path(self.tmp.name) / "outside.txt")
        Path(outside).write_text("secret")
        result = self._run(host, "file_read", {"path": outside})
        # governance allows the READ capability, but the FS scope denies the path
        self.assertFalse(result.value.success)
        self.assertIn("scope", result.value.error)

    def test_process_list_read_auto_allows(self):
        result = self._run(self._host(), "process_list", {})
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertGreater(result.value.normalized["total"], 0)

    def test_external_command_and_session_recheck_guard_after_preparation(self) -> None:
        for capability in ("shell_command", "session_exec"):
            with self.subTest(capability=capability):
                provider = _MappedSessionProvider(self.root)
                coordinator = _coordinator(Path(self.tmp.name), PermissionMode.AUTO)
                host = HostController(
                    coordinator, self.scope, CommandPolicy(), executor=provider
                )
                changed = False

                def guard() -> str:
                    return "scope changed during preparation" if changed else ""

                coordinator.set_pre_execution_check(guard)
                original = host._recheck_executables

                async def prepare(action: Any) -> Any:
                    nonlocal changed
                    result = await original(action)
                    await asyncio.sleep(0)
                    changed = True
                    return result

                host._recheck_executables = prepare
                params = {"argv": ["pwd"]}
                if capability == "session_exec":
                    opened = self._run(host, "session_open", {"cwd": str(self.root)})
                    self.assertEqual(opened.status, ExecutionStatus.SUCCESS)
                result = self._run(host, capability, params)
                self.assertEqual(result.status, ExecutionStatus.BLOCKED)
                self.assertEqual(provider.commands, [])
                self.assertIn("scope changed", result.error)
                self.assertTrue(coordinator._logging.get_logs(tool_filter=capability))
                self.assertTrue(
                    coordinator._feedback.get_execution_feedback(capability)
                )
                self.assertTrue(coordinator._audit.query(event_type="rejection"))

    def test_external_launch_rechecks_actual_host_restrictions(self) -> None:
        for capability in ("shell_command", "session_exec"):
            for mutation in ("scope", "policy", "provider", "mapping", "session"):
                if mutation == "session" and capability != "session_exec":
                    continue
                with self.subTest(capability=capability, mutation=mutation):
                    provider = _MappedSessionProvider(self.root)
                    coordinator = _coordinator(Path(self.tmp.name), PermissionMode.AUTO)
                    host = HostController(
                        coordinator, self.scope, CommandPolicy(), executor=provider
                    )
                    if capability == "session_exec":
                        opened = self._run(
                            host, "session_open", {"cwd": str(self.root)}
                        )
                        self.assertTrue(opened.success)
                    original = host._recheck_executables

                    async def prepare(action: Any) -> Any:
                        result = await original(action)
                        await asyncio.sleep(0)
                        if mutation == "scope":
                            host.set_scope(FilesystemScope(), host._policy)
                        elif mutation == "policy":
                            host.set_scope(self.scope, None)
                        elif mutation == "provider":
                            host._executor = _MappedSessionProvider(self.root)
                        elif mutation == "mapping":
                            provider._mappings = ()
                        else:
                            host._provider_session.context = ExecutionContext(
                                cwd="/other"
                            )
                        return result

                    host._recheck_executables = prepare
                    result = self._run(host, capability, {"argv": ["pwd"]})
                    self.assertFalse(result.success)
                    self.assertEqual(provider.commands, [])
                    self.assertTrue(
                        coordinator._logging.get_logs(tool_filter=capability)
                    )
                    self.assertTrue(
                        coordinator._feedback.get_execution_feedback(capability)
                    )
                    self.assertTrue(
                        coordinator._audit.query(event_type="tool_execution")
                    )

    def test_plan_mode_denies_execution(self):
        host = self._host(mode=PermissionMode.PLAN)
        result = self._run(host, "file_read", {"path": str(self.root / "x")})
        self.assertEqual(result.status, ExecutionStatus.DENIED)

    def test_auto_mode_writes_without_prompt(self):
        # a coordinator with NO approval callback still succeeds in AUTO mode
        coord = _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO)
        coord._approval_callback = None
        host = HostController(coord, self.scope, CommandPolicy())
        result = self._run(
            host, "file_write", {"path": str(self.root / "a.txt"), "content": "x"}
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)

    def test_mode_setters_change_gate_behavior_at_runtime(self):
        # the /agent loop relies on set_mode/get_mode to apply and restore mode
        coord = _coordinator(Path(self.tmp.name), mode=PermissionMode.ASK)
        self.assertEqual(coord.get_mode(), PermissionMode.ASK)
        host = HostController(coord, self.scope, CommandPolicy())

        coord.set_mode(PermissionMode.PLAN)
        denied = self._run(host, "process_list", {})  # READ, but plan mode denies
        self.assertEqual(denied.status, ExecutionStatus.DENIED)

        coord.set_mode(PermissionMode.ASK)
        allowed = self._run(host, "process_list", {})
        self.assertEqual(allowed.status, ExecutionStatus.SUCCESS)

    def test_destructive_shell_command_is_gated(self):
        # rm -rf classifies DESTRUCTIVE -> gate denies without an engagement override
        host = self._host(allow_destructive=False)
        result = self._run(
            host, "shell_command", {"command": "rm -rf " + str(self.root / "x")}
        )
        self.assertNotEqual(result.status, ExecutionStatus.SUCCESS)

    def test_shell_command_accepts_command_string(self):
        host = self._host(mode=PermissionMode.AUTO)
        command = f'"{sys.executable}" -c "print(\'hello-from-string\')"'
        result = self._run(host, "shell_command", {"command": command})
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertIn("hello-from-string", result.value.normalized["stdout"])

    def test_shell_command_accepts_argv_list(self):
        # argv is the advertised alternative to command; both must reach the tool.
        host = self._host(mode=PermissionMode.AUTO)
        result = self._run(
            host,
            "shell_command",
            {"argv": [sys.executable, "-c", "print('hello-from-argv')"]},
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertIn("hello-from-argv", result.value.normalized["stdout"])

    def test_unclassified_cli_effect_requires_write_approval(self) -> None:
        audit = AuditLayer(Path(self.tmp.name) / "unknown-effect-audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(
                ScopePolicy(allow_all=True),
                audit=audit,
                mode=PermissionMode.ASK,
            ),
            audit=audit,
        )
        host = HostController(coordinator, self.scope, CommandPolicy())

        result = self._run(
            host,
            "shell_command",
            {"argv": [sys.executable, "-c", "print('safe')"]},
        )

        self.assertEqual(result.status, ExecutionStatus.DENIED)
        self.assertIn("approval", result.error)
        self.assertEqual(result.action, "shell_command")

    def test_list_tools_discovers_installed_binaries(self):
        result = self._run(self._host(), "list_tools", {})
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        data = result.value.normalized
        self.assertGreater(data["count"], 0)
        # each entry is a name + resolved path on $PATH
        self.assertTrue(all(t.get("name") and t.get("path") for t in data["tools"]))
        self.assertTrue(data["path_dirs"])

    def test_list_tools_honors_query_filter(self):
        result = self._run(self._host(), "list_tools", {"query": "sh"})
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        names = [t["name"] for t in result.value.normalized["tools"]]
        self.assertTrue(names, "expected at least one 'sh'-matching tool")
        self.assertTrue(all("sh" in n.lower() for n in names))

    def test_exact_local_discovery_fingerprints_one_executable(self):
        available = self._run(self._host(), "list_tools", {"limit": 1})
        name = available.value.normalized["tools"][0]["name"]
        inspected = self._run(self._host(), "list_tools", {"exact": name})
        self.assertEqual(inspected.status, ExecutionStatus.SUCCESS)
        tool = inspected.value.normalized["tools"][0]
        self.assertEqual(tool["name"], name)
        self.assertRegex(tool["sha256"], r"^[a-f0-9]{64}$")

    def test_exact_discovery_rejects_path_instead_of_name(self):
        result = self._run(self._host(), "list_tools", {"exact": "../tool"})
        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertIn("basename", result.error)

    def test_exact_discovery_reports_missing_tool_without_installing(self):
        result = self._run(
            self._host(),
            "list_tools",
            {"exact": "decode-missing-provider-probe-9f08"},
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.value.normalized["tools"], [])
        self.assertEqual(result.value.normalized["count"], 0)

    def test_missing_tool_reports_not_found_without_crashing(self):
        host = self._host(mode=PermissionMode.AUTO)
        result = self._run(
            host, "shell_command", {"argv": ["decode-nonexistent-tool-xyz"]}
        )
        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("Required dependency missing", result.error)
        self.assertIn("Installation was not attempted", result.error)

    def test_nonzero_command_exit_is_execution_failure(self):
        host = self._host(mode=PermissionMode.AUTO)
        result = self._run(
            host,
            "shell_command",
            {"argv": [sys.executable, "-c", "raise SystemExit(9)"]},
        )
        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertFalse(result.success)
        self.assertEqual(result.value.normalized["exit_code"], 9)

    def test_unknown_parameters_are_rejected_before_execution(self):
        result = self._run(
            self._host(),
            "list_tools",
            {"query": "python", "surprise": True},
        )
        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("unsupported normalized arguments", result.error)

    def test_shell_operator_is_rejected_before_execution(self):
        result = self._run(
            self._host(mode=PermissionMode.AUTO),
            "shell_command",
            {"argv": ["echo", "hello", "|", "decode-must-not-run"]},
        )
        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("shell operator", result.error)

    def test_curl_output_must_be_inside_write_scope(self):
        outside = Path(self.tmp.name) / "outside" / "page.html"
        result = self._run(
            self._host(mode=PermissionMode.AUTO),
            "shell_command",
            {
                "argv": [
                    "curl",
                    "https://example.test",
                    "-o",
                    str(outside),
                ]
            },
        )
        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("authorized write scope", result.error)

    def test_discovery_and_execution_use_the_same_selected_provider(self):
        class FakeProvider(ExecutionProvider):
            def __init__(self):
                self.commands = []

            @property
            def name(self):
                return "wsl/kali-linux"

            async def execute(self, command, timeout=60, env=None):
                self.commands.append(command)
                if command == ["/usr/bin/printenv", "PATH"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout="/usr/bin:/bin\n",
                    )
                if command[:1] == ["/usr/bin/find"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout="f\tcurl\t/usr/bin/curl\n",
                    )
                if command[:1] == ["/usr/bin/sha256sum"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout=f"{'a' * 64}  /usr/bin/curl\n",
                    )
                return ExecutionResult(
                    command=command,
                    provider=self.name,
                    success=True,
                    stdout="provider-bound\n",
                )

            async def check_health(self):
                return True

        provider = FakeProvider()
        coord = _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO)
        host = HostController(
            coord,
            self.scope,
            CommandPolicy(),
            executor=provider,
        )

        discovered = self._run(host, "list_tools", {"query": "curl"})
        executed = self._run(host, "shell_command", {"argv": ["curl", "--version"]})

        self.assertEqual(discovered.status, ExecutionStatus.SUCCESS)
        self.assertEqual(discovered.value.normalized["provider"], "wsl/kali-linux")
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS)
        self.assertEqual(executed.value.provider, "wsl/kali-linux")
        self.assertEqual(provider.commands[-1], ["/usr/bin/curl", "--version"])
        self.assertEqual(
            provider.commands.count(["/usr/bin/sha256sum", "/usr/bin/curl"]),
            2,
        )

        inspected = self._run(host, "list_tools", {"exact": "curl"})
        self.assertEqual(inspected.status, ExecutionStatus.SUCCESS)
        self.assertEqual(inspected.value.normalized["tools"][0]["sha256"], "a" * 64)
        self.assertEqual(provider.commands[-1], ["/usr/bin/sha256sum", "/usr/bin/curl"])

    def test_provider_discovery_rejects_relative_path_without_scanning(self):
        class InvalidPathProvider(ExecutionProvider):
            def __init__(self):
                self.commands = []

            @property
            def name(self):
                return "wsl/kali-linux"

            async def execute(self, command, timeout=60, env=None):
                self.commands.append(command)
                return ExecutionResult(
                    command=command,
                    provider=self.name,
                    success=True,
                    stdout="relative:/usr/bin\n",
                )

            async def check_health(self):
                return True

        provider = InvalidPathProvider()
        host = HostController(
            _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO),
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        result = self._run(host, "list_tools", {"query": "curl"})
        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertIn("invalid PATH", result.error)
        self.assertEqual(provider.commands, [["/usr/bin/printenv", "PATH"]])

    def test_partial_provider_scan_preserves_output_and_does_not_fingerprint(self):
        class PartialProvider(ExecutionProvider):
            def __init__(self):
                self.commands = []

            @property
            def name(self):
                return "wsl/kali-linux"

            async def execute(self, command, timeout=60, env=None):
                self.commands.append(command)
                if command == ["/usr/bin/printenv", "PATH"]:
                    return ExecutionResult(
                        provider=self.name, success=True, stdout="/usr/bin\n"
                    )
                return ExecutionResult(
                    provider=self.name,
                    success=False,
                    stdout="f\tcurl\t/usr/bin/curl\n",
                    exit_code=1,
                    error="path scan incomplete",
                )

            async def check_health(self):
                return True

        provider = PartialProvider()
        host = HostController(
            _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO),
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        result = self._run(host, "list_tools", {"query": "curl"})
        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertTrue(result.value.partial)
        self.assertIn("/usr/bin/curl", result.value.stdout)
        self.assertEqual(len(provider.commands), 2)

    def test_provider_discovery_filters_stale_path_and_retries(self):
        class StalePathProvider(ExecutionProvider):
            def __init__(self):
                self.commands = []

            @property
            def name(self):
                return "wsl/kali-linux"

            async def execute(self, command, timeout=60, env=None):
                self.commands.append(command)
                if command == ["/usr/bin/printenv", "PATH"]:
                    return ExecutionResult(
                        provider=self.name,
                        success=True,
                        stdout="/usr/bin:/missing/windows/bin\n",
                    )
                if command == ["/usr/bin/test", "-d", "/usr/bin"]:
                    return ExecutionResult(provider=self.name, success=True)
                if command == ["/usr/bin/test", "-d", "/missing/windows/bin"]:
                    return ExecutionResult(provider=self.name, success=False)
                if command[:1] == ["/usr/bin/find"]:
                    if "/missing/windows/bin" in command:
                        return ExecutionResult(
                            provider=self.name,
                            success=False,
                            exit_code=1,
                            stdout="f\tcurl\t/usr/bin/curl\n",
                            stderr="missing directory",
                        )
                    return ExecutionResult(
                        provider=self.name,
                        success=True,
                        stdout="f\tcurl\t/usr/bin/curl\n",
                    )
                raise AssertionError(command)

            async def check_health(self):
                return True

        provider = StalePathProvider()
        host = HostController(
            _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO),
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        result = self._run(host, "list_tools", {"query": "curl"})
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.value.normalized["tools"][0]["path"], "/usr/bin/curl")
        self.assertNotIn("/missing/windows/bin", provider.commands[-1])

    def test_mapped_external_output_is_scoped_rewritten_and_bound(self):
        class FakeMappedProvider(ExecutionProvider):
            def __init__(self, root: Path) -> None:
                self.commands: list[list[str]] = []
                self.contexts: list[ExecutionContext | None] = []
                self._mappings = (
                    ProviderPathMapping(
                        host_root=str(root),
                        provider_root="/workspace",
                        writable=True,
                    ),
                )

            @property
            def name(self) -> str:
                return "wsl/kali-linux"

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
                    cwd=True,
                    environment=True,
                    path_mapping=True,
                    scoped_filesystem=True,
                )

            async def execute(
                self,
                command,
                timeout=60,
                env=None,
                context=None,
            ) -> ExecutionResult:
                self.commands.append(list(command))
                if command == ["/usr/bin/printenv", "PATH"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout="/usr/bin\n",
                    )
                if command[:1] == ["/usr/bin/find"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout="f\tcurl\t/usr/bin/curl\n",
                    )
                if command[:1] == ["/usr/bin/sha256sum"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout=f"{'b' * 64}  /usr/bin/curl\n",
                    )
                if (
                    len(command) == 3
                    and command[0] == "/usr/bin/test"
                    and command[1] in {"-f", "-x"}
                ):
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                    )
                self.contexts.append(context)
                return ExecutionResult(
                    command=command,
                    provider=self.name,
                    success=True,
                    stdout="mapped\n",
                )

            async def check_health(self) -> bool:
                return True

        provider = FakeMappedProvider(self.root)
        host = HostController(
            _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO),
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        output = self.root / "page.html"

        result = self._run(
            host,
            "shell_command",
            {
                "argv": [
                    "curl",
                    "https://example.test/page.html",
                    "-o",
                    str(output),
                ]
            },
        )

        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(provider.commands[-1][-1], "/workspace/page.html")
        self.assertEqual(
            provider.contexts[0].declared_outputs,
            ("/workspace/page.html",),
        )

    def test_mapped_shell_action_reaches_approval_and_telemetry(self) -> None:
        approvals: list[Any] = []
        root = Path(self.tmp.name)
        audit = AuditLayer(root / "resolved-action-audit")
        logging = LoggingService(root / "resolved-action-logs")
        coordinator = ExecutionCoordinator(
            GovernanceGate(
                ScopePolicy(allow_all=True),
                audit=audit,
                mode=PermissionMode.ASK,
            ),
            approval_callback=lambda request: not approvals.append(request),
            audit=audit,
            logging_service=logging,
        )
        provider = _MappedSessionProvider(self.root)
        host = HostController(
            coordinator,
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        output = self.root / "page.html"

        result = self._run(
            host,
            "shell_command",
            {"argv": ["curl", "https://example.test/page", "-o", str(output)]},
        )

        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        approved = approvals[0]
        action = approved.resolved_action
        self.assertEqual(action["provider"], provider.name)
        self.assertEqual(action["tool"], "curl")
        self.assertEqual(action["tool_version"], "")
        self.assertEqual(action["target"], "https://example.test/page")
        self.assertEqual(action["argv"][0], "/usr/bin/curl")
        self.assertEqual(action["argv"][-1], "/workspace/page.html")
        self.assertEqual(action["executables"][0]["path"], "/usr/bin/curl")
        self.assertEqual(action["executables"][0]["sha256"], "c" * 64)
        self.assertEqual(action["outputs"][0]["host"], str(output))
        self.assertEqual(action["outputs"][0]["provider"], "/workspace/page.html")
        self.assertEqual(
            action["side_effects"],
            ["filesystem_write", "network"],
        )
        self.assertEqual(action["timeout_seconds"], 60)
        self.assertEqual(approved.execution_identity.tool, "curl")
        self.assertEqual(
            approved.execution_identity.executable_path,
            "/usr/bin/curl",
        )
        self.assertEqual(
            approved.execution_identity.executable_sha256,
            "c" * 64,
        )
        self.assertEqual(
            logging.get_logs(tool_filter="shell_command")[0]["metadata"][
                "resolved_action"
            ]["output_count"],
            1,
        )
        action_log = logging.get_logs(tool_filter="shell_command")[0]["metadata"][
            "resolved_action"
        ]
        self.assertTrue(action_log["executable_verified"])
        self.assertEqual(action_log["executable_count"], 1)
        self.assertNotIn("executable_path", action_log)

    def test_changed_provider_executable_is_denied_before_launch(self) -> None:
        class ChangingProvider(ExecutionProvider):
            def __init__(self) -> None:
                self.hash_count = 0
                self.launched = False

            @property
            def name(self) -> str:
                return "wsl/kali-linux"

            async def execute(self, command, timeout=60, env=None, context=None):
                if command == ["/usr/bin/printenv", "PATH"]:
                    return ExecutionResult(
                        provider=self.name, success=True, stdout="/usr/bin\n"
                    )
                if command[:1] == ["/usr/bin/find"]:
                    return ExecutionResult(
                        provider=self.name,
                        success=True,
                        stdout="f\tprobe\t/usr/bin/probe\n",
                    )
                if command[:1] == ["/usr/bin/sha256sum"]:
                    self.hash_count += 1
                    digest = "d" * 64 if self.hash_count == 1 else "e" * 64
                    return ExecutionResult(
                        provider=self.name,
                        success=True,
                        stdout=f"{digest}  /usr/bin/probe\n",
                    )
                if (
                    len(command) == 3
                    and command[0] == "/usr/bin/test"
                    and command[1] in {"-f", "-x"}
                ):
                    return ExecutionResult(provider=self.name, success=True)
                self.launched = True
                return ExecutionResult(provider=self.name, success=True)

            async def check_health(self):
                return True

        provider = ChangingProvider()
        host = HostController(
            _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO),
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        result = self._run(host, "shell_command", {"argv": ["probe", "--help"]})
        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertEqual(result.error, "executable_identity_changed")
        self.assertFalse(provider.launched)

    def test_sudo_and_wrapped_executable_are_both_approval_bound(self) -> None:
        approvals: list[Any] = []
        audit = AuditLayer(Path(self.tmp.name) / "sudo-identity-audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(
                ScopePolicy(allow_all=True),
                audit=audit,
                mode=PermissionMode.ASK,
            ),
            approval_callback=lambda request: not approvals.append(request),
            audit=audit,
        )
        provider = _MappedSessionProvider(self.root)
        host = HostController(
            coordinator,
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        output = self.root / "sudo-result.txt"
        result = self._run(
            host,
            "shell_command",
            {"argv": ["sudo", "touch", str(output)]},
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        action = approvals[0].resolved_action
        self.assertEqual(
            action["argv"],
            ["/usr/bin/sudo", "/usr/bin/touch", "/workspace/sudo-result.txt"],
        )
        self.assertEqual(
            [item["argv_index"] for item in action["executables"]],
            [0, 1],
        )
        self.assertEqual(len(action["executables"]), 2)

    def test_unmapped_external_output_remains_fail_closed(self):
        class FakeUnmappedProvider(ExecutionProvider):
            def __init__(self) -> None:
                self.called = False

            @property
            def name(self) -> str:
                return "wsl/kali-linux"

            @property
            def filesystem_mode(self) -> FilesystemMode:
                return FilesystemMode.MAPPED

            async def execute(
                self,
                command,
                timeout=60,
                env=None,
                context=None,
            ) -> ExecutionResult:
                self.called = True
                return ExecutionResult(command=command, success=True)

            async def check_health(self) -> bool:
                return True

        provider = FakeUnmappedProvider()
        host = HostController(
            _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO),
            self.scope,
            CommandPolicy(),
            executor=provider,
        )

        result = self._run(
            host,
            "shell_command",
            {
                "argv": [
                    "curl",
                    "https://example.test/page.html",
                    "-o",
                    str(self.root / "page.html"),
                ]
            },
        )

        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("no mapping", result.error)
        self.assertFalse(provider.called)

    def test_provider_session_binds_identity_cwd_outputs_and_approval(self) -> None:
        approvals: list[Any] = []
        audit = AuditLayer(Path(self.tmp.name) / "session-audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(
                ScopePolicy(allow_all=True),
                audit=audit,
                mode=PermissionMode.ASK,
            ),
            approval_callback=lambda request: not approvals.append(request),
            audit=audit,
        )
        provider = _MappedSessionProvider(self.root)
        host = HostController(
            coordinator,
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        subdirectory = self.root / "sub"
        subdirectory.mkdir()

        opened = self._run(
            host,
            "session_open",
            {"cwd": str(self.root)},
        )
        first = self._run(host, "session_exec", {"argv": ["pwd"]})
        changed = self._run(host, "session_exec", {"argv": ["cd", "sub"]})
        output = subdirectory / "result.txt"
        written = self._run(
            host,
            "session_exec",
            {"argv": ["touch", str(output)]},
        )
        closed = self._run(host, "session_close", {})

        self.assertEqual(opened.status, ExecutionStatus.SUCCESS)
        session_id = opened.value.normalized["session_id"]
        self.assertEqual(opened.value.normalized["provider"], provider.name)
        self.assertEqual(opened.value.normalized["provider_cwd"], "/workspace")
        self.assertEqual(first.status, ExecutionStatus.SUCCESS)
        self.assertEqual(changed.value.normalized["cwd"], str(subdirectory))
        self.assertEqual(changed.value.normalized["provider_cwd"], "/workspace/sub")
        self.assertEqual(written.status, ExecutionStatus.SUCCESS)
        self.assertEqual(provider.commands[0], ["/usr/bin/pwd"])
        self.assertEqual(
            provider.commands[1],
            ["/usr/bin/test", "-d", "/workspace/sub"],
        )
        self.assertEqual(
            provider.commands[2],
            ["/usr/bin/touch", "/workspace/sub/result.txt"],
        )
        self.assertEqual(provider.contexts[2].cwd, "/workspace/sub")
        self.assertEqual(
            provider.contexts[2].declared_outputs,
            ("/workspace/sub/result.txt",),
        )
        write_approval = approvals[-1]
        self.assertEqual(write_approval.params["session_id"], session_id)
        self.assertEqual(write_approval.params["provider"], provider.name)
        self.assertEqual(write_approval.params["_host_cwd"], str(subdirectory))
        self.assertEqual(
            write_approval.params["_provider_outputs"],
            ["/workspace/sub/result.txt"],
        )
        self.assertEqual(
            write_approval.resolved_action["outputs"][0]["provider"],
            "/workspace/sub/result.txt",
        )
        self.assertEqual(
            write_approval.resolved_action["cwd"],
            "/workspace/sub",
        )
        self.assertEqual(closed.value.normalized["session_id"], session_id)
        self.assertEqual(closed.value.normalized["commands_run"], 3)

    def test_provider_session_revalidates_scope_before_each_command(self) -> None:
        provider = _MappedSessionProvider(self.root)
        host = HostController(
            _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO),
            self.scope,
            CommandPolicy(),
            executor=provider,
        )
        opened = self._run(
            host,
            "session_open",
            {"cwd": str(self.root)},
        )
        self.assertEqual(opened.status, ExecutionStatus.SUCCESS)

        host.set_scope(FilesystemScope(), CommandPolicy())
        blocked = self._run(host, "session_exec", {"argv": ["pwd"]})

        self.assertEqual(blocked.status, ExecutionStatus.BLOCKED)
        self.assertIn("authorized read scope", blocked.error)
        self.assertEqual(provider.commands, [])

    def test_external_provider_does_not_fall_back_for_stateful_session(self):
        class FakeProvider(ExecutionProvider):
            @property
            def name(self):
                return "wsl/kali-linux"

            async def execute(self, command, timeout=60, env=None):
                raise AssertionError("provider must not be called")

            async def check_health(self):
                return True

        coord = _coordinator(Path(self.tmp.name), mode=PermissionMode.AUTO)
        host = HostController(
            coord,
            self.scope,
            CommandPolicy(),
            executor=FakeProvider(),
        )

        result = self._run(host, "session_open", {})

        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("no local fallback", result.error)

    def test_network_command_target_must_be_in_engagement_scope(self):
        class FakeProvider(ExecutionProvider):
            def __init__(self):
                self.called = False

            @property
            def name(self):
                return "wsl/kali-linux"

            async def execute(self, command, timeout=60, env=None):
                self.called = True
                return ExecutionResult(
                    command=command,
                    provider=self.name,
                    success=True,
                    stdout="must not execute",
                )

            async def check_health(self):
                return True

        provider = FakeProvider()
        audit = AuditLayer(Path(self.tmp.name) / "target-audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(
                ScopePolicy(allowed=["allowed.example.test"]),
                audit=audit,
                mode=PermissionMode.AUTO,
            ),
            audit=audit,
        )
        host = HostController(
            coordinator,
            self.scope,
            CommandPolicy(),
            executor=provider,
        )

        result = self._run(
            host,
            "shell_command",
            {"argv": ["curl", "https://outside.example.test/status"]},
        )

        self.assertEqual(result.status, ExecutionStatus.DENIED)
        self.assertFalse(provider.called)
        self.assertIn("out of engagement scope", result.error)

    def test_session_parameters_are_strictly_validated(self):
        result = self._run(
            self._host(mode=PermissionMode.AUTO),
            "session_open",
            {"cwd": str(self.root), "surprise": True},
        )

        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("unsupported normalized arguments", result.error)

    def test_network_command_is_denied_inside_local_session(self):
        result = self._run(
            self._host(mode=PermissionMode.AUTO),
            "session_exec",
            {"argv": ["curl", "https://allowed.example.test"]},
        )

        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("use shell_command with an explicit target", result.error)

    def test_local_session_binds_executable_context_and_cd_to_approval(self):
        approvals: list[Any] = []
        audit = AuditLayer(Path(self.tmp.name) / "local-session-audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(
                ScopePolicy(allow_all=True), audit=audit, mode=PermissionMode.ASK
            ),
            approval_callback=lambda request: not approvals.append(request),
            audit=audit,
        )
        host = HostController(coordinator, self.scope, CommandPolicy())
        subdirectory = self.root / "sub"
        subdirectory.mkdir()
        self.assertEqual(
            self._run(host, "session_open", {"cwd": str(self.root)}).status,
            ExecutionStatus.SUCCESS,
        )

        command = self._run(
            host, "session_exec", {"argv": [sys.executable, "--version"]}
        )
        self.assertEqual(command.status, ExecutionStatus.SUCCESS)
        bound = approvals[-1]
        executable = host_ops.inspect_executable(sys.executable)
        self.assertEqual(bound.resolved_action["argv"][0], executable["path"])
        self.assertEqual(
            bound.execution_identity.executable_sha256, executable["sha256"]
        )
        self.assertEqual(bound.resolved_action["cwd"], str(self.root))
        self.assertEqual(
            bound.resolved_action["executables"][0]["path"], executable["path"]
        )
        self.assertEqual(len(bound.params["_environment_sha256"]), 64)

        changed = self._run(host, "session_exec", {"argv": ["cd", "sub"]})
        self.assertEqual(changed.status, ExecutionStatus.SUCCESS)
        self.assertEqual(changed.value.normalized["cwd"], str(subdirectory))
        self.assertEqual(approvals[-1].params["_next_cwd"], str(subdirectory))
        self.assertEqual(approvals[-1].resolved_action["cwd"], str(self.root))

    def test_local_session_denies_changed_executable_after_approval(self):
        host = self._host()
        self.assertEqual(
            self._run(host, "session_open", {"cwd": str(self.root)}).status,
            ExecutionStatus.SUCCESS,
        )
        original = host_ops.inspect_executable
        inspected = 0

        def changing_identity(executable, *, search_path=None):
            nonlocal inspected
            inspected += 1
            identity = original(executable, search_path=search_path)
            if inspected > 1:
                identity["sha256"] = "0" * 64
            return identity

        with (
            patch.object(host_ops, "inspect_executable", side_effect=changing_identity),
            patch.object(HostSession, "run") as run,
        ):
            result = self._run(
                host, "session_exec", {"argv": [sys.executable, "--version"]}
            )

        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertIn("executable_identity_changed", result.error)
        run.assert_not_called()

    def test_local_session_missing_executable_does_not_install_or_launch(self):
        host = self._host()
        self.assertEqual(
            self._run(host, "session_open", {"cwd": str(self.root)}).status,
            ExecutionStatus.SUCCESS,
        )
        with patch.object(HostSession, "run") as run:
            result = self._run(
                host, "session_exec", {"argv": ["decode-absent-tool-59183"]}
            )
        self.assertEqual(result.status, ExecutionStatus.BLOCKED)
        self.assertIn("Required dependency missing", result.error)
        run.assert_not_called()

    def test_local_session_binds_relative_output_and_denies_context_change(self):
        approvals: list[Any] = []
        audit = AuditLayer(Path(self.tmp.name) / "local-output-audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(
                ScopePolicy(allow_all=True), audit=audit, mode=PermissionMode.ASK
            ),
            audit=audit,
        )
        host = HostController(coordinator, self.scope, CommandPolicy())
        self.assertEqual(
            self._run(host, "session_open", {"cwd": str(self.root)}).status,
            ExecutionStatus.SUCCESS,
        )

        def change_context(request):
            approvals.append(request)
            host._session.cwd = str(Path(self.tmp.name))
            return True

        coordinator.set_approval_callback(change_context)
        with patch.object(HostSession, "run") as run:
            result = self._run(
                host,
                "session_exec",
                {"argv": [sys.executable, "-o", "result.txt"]},
            )

        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertIn("session_context_changed", result.error)
        self.assertEqual(
            approvals[-1].resolved_action["outputs"],
            [
                {
                    "host": str(self.root / "result.txt"),
                    "provider": str(self.root / "result.txt"),
                }
            ],
        )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
