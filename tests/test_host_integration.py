import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from decode.audit import AuditLayer
from decode.execution import ExecutionProvider, ExecutionResult
from decode.governance import GovernanceGate, ScopePolicy
from decode.hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
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

    def test_missing_tool_reports_not_found_without_crashing(self):
        host = self._host(mode=PermissionMode.AUTO)
        result = self._run(
            host, "shell_command", {"argv": ["decode-nonexistent-tool-xyz"]}
        )
        # a missing tool is reported, never a crash or a governance bypass
        self.assertFalse(result.value.success)
        self.assertIn("not found", result.value.error.lower())

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
                if command == ["/usr/bin/env"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout="PATH=/usr/bin:/bin\n",
                    )
                if command[:1] == ["/usr/bin/find"]:
                    return ExecutionResult(
                        command=command,
                        provider=self.name,
                        success=True,
                        stdout="f\tcurl\t/usr/bin/curl\n",
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
        self.assertEqual(
            discovered.value.normalized["provider"], "wsl/kali-linux"
        )
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS)
        self.assertEqual(executed.value.provider, "wsl/kali-linux")
        self.assertEqual(len(provider.commands), 3)

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


if __name__ == "__main__":
    unittest.main()
