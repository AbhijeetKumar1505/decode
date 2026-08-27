import asyncio
import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.audit import AuditLayer
from decode.bootstrap.engine import BootstrapEngine
from decode.execution import (
    ExecutionResult,
    LocalExecutor,
    DockerExecutor,
    WSLExecutor,
    SSHExecutor,
    MCPExecutor,
    create_executor,
    available_provider_names,
)
from decode.execution.base import require_governed_external_io
from decode.governance import GovernanceGate, ScopePolicy
from decode.runtime import ExecutionCoordinator, ExecutionRequest
from decode.skills.base import RiskLevel


def _run_provider(executor, command, timeout=60, authorized_executor=None):
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
            return await executor.execute(command, timeout=timeout)

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
        r = ExecutionResult(command="sleep 99", success=False, timed_out=True, duration=5.0)
        self.assertIn("Timed out", r.summary)

    def test_argument_vector_has_a_stable_display_and_versioned_result(self):
        result = ExecutionResult(command=["scanner", "target; harmless"])

        self.assertEqual(result.command, "scanner 'target; harmless'")
        self.assertRegex(result.schema_version, r"^\d+\.\d+\.\d+$")


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
        argv = WSLExecutor(distro="Lab")._wsl_argv(
            ["scanner", "target; harmless"]
        )

        self.assertEqual(
            argv,
            ["wsl.exe", "-d", "Lab", "--", "scanner", "target; harmless"],
        )

    def test_ssh_argument_vector_is_quoted_as_one_remote_command(self):
        argv = SSHExecutor(host="192.0.2.10")._ssh_argv(
            ["scanner", "target; harmless"]
        )

        self.assertEqual(argv[-1], "scanner 'target; harmless'")


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
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "decode.bootstrap.engine.subprocess.run"
        ) as run:
            engine = BootstrapEngine(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
                engine.system_update()

        run.assert_not_called()


class TestPublicExecutionBoundaryInventory(unittest.TestCase):
    ENTRY_METHODS = {
        "execute",
        "execute_command",
        "execute_plugin",
        "execute_registered_skill",
        "run",
        "system_update",
    }
    EXPLICIT_BOUNDARIES = {
        ("bootstrap/engine.py", "BootstrapEngine", "run"),
        ("bootstrap/engine.py", "BootstrapEngine", "system_update"),
        ("runtime/coordinator.py", "ExecutionCoordinator", "execute"),
        ("skills/registry.py", "SkillRegistry", "execute"),
        ("tools.py", "PluginManager", "execute_plugin"),
        ("tools.py", "_SkillAdapter", "execute"),
        ("tui/app.py", "AgentREPL", "run"),
        # Host-control surfaces: HostController routes through the coordinator;
        # ToolUseLoop delegates execution to a coordinator-backed invoke; HostSession
        # runs only inside HostAgent's coordinator-governed execute_internal.
        ("runtime/host_controller.py", "HostController", "run"),
        ("runtime/agent_loop.py", "ToolUseLoop", "run"),
        ("hostcontrol/session.py", "HostSession", "run"),
        ("universal_agent.py", "UniversalAgent", "execute_command"),
        (
            "universal_agent.py",
            "UniversalAgent",
            "execute_registered_skill",
        ),
    }

    def test_every_public_execution_entry_point_has_a_known_boundary(self):
        package_root = Path(__file__).parents[1] / "decode"
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
                            relative.startswith("plugins/")
                            and method.name == "execute"
                        )
                        or (
                            relative.startswith("execution/")
                            and method.name == "execute"
                        )
                        or (
                            relative.startswith("agents/") and method.name == "run"
                        )
                    )
                    if not wrapped_family and entry not in self.EXPLICIT_BOUNDARIES:
                        unclassified.append(entry)

        self.assertTrue(self.EXPLICIT_BOUNDARIES <= discovered)
        self.assertEqual(unclassified, [])


if __name__ == "__main__":
    unittest.main()
