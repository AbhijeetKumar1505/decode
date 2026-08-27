import asyncio
import tempfile
import unittest
from pathlib import Path

from decode.audit import AuditLayer
from decode.governance import GovernanceGate, ScopePolicy
from decode.hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from decode.runtime import ExecutionCoordinator, HostController
from decode.runtime.coordinator import ExecutionStatus


def _coordinator(tmp: Path, mode: PermissionMode = PermissionMode.ASK, allow_destructive: bool = False):
    audit = AuditLayer(tmp / "audit")
    gate = GovernanceGate(ScopePolicy(allow_all=True), audit=audit, allow_destructive=allow_destructive, mode=mode)
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
        coord = _coordinator(Path(self.tmp.name), mode=mode, allow_destructive=allow_destructive)
        return HostController(coord, self.scope, policy if policy is not None else CommandPolicy())

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

        edit = self._run(host, "file_edit", {"path": path, "old": "world", "new": "there"})
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
        result = self._run(host, "file_write", {"path": str(self.root / "a.txt"), "content": "x"})
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
        result = self._run(host, "shell_command", {"command": "rm -rf " + str(self.root / "x")})
        self.assertNotEqual(result.status, ExecutionStatus.SUCCESS)

    def test_shell_command_accepts_command_string(self):
        host = self._host(mode=PermissionMode.AUTO)
        result = self._run(host, "shell_command", {"command": "echo hello-from-string"})
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertIn("hello-from-string", result.value.normalized["stdout"])

    def test_shell_command_accepts_argv_list(self):
        # argv is the advertised alternative to command; both must reach the tool.
        host = self._host(mode=PermissionMode.AUTO)
        result = self._run(host, "shell_command", {"argv": ["echo", "hello-from-argv"]})
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
        result = self._run(host, "shell_command", {"argv": ["decode-nonexistent-tool-xyz"]})
        # a missing tool is reported, never a crash or a governance bypass
        self.assertFalse(result.value.success)
        self.assertIn("not found", result.value.error.lower())


if __name__ == "__main__":
    unittest.main()
