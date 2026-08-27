import sys
import tempfile
import unittest
from pathlib import Path

from decode.hostcontrol import (
    CommandPolicy,
    FilesystemScope,
    HookEvent,
    HookRegistry,
    HostSession,
    PermissionMode,
    resolve_mode_decision,
)
from decode.hostcontrol import operations as ops
from decode.hostcontrol.mcp import host_capability_tools
from decode.skills.base import RiskLevel


class TestFilesystemScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scope = FilesystemScope(read_roots=[self.root / "ro"], write_roots=[self.root / "rw"])
        (self.root / "ro").mkdir()
        (self.root / "rw").mkdir()

    def test_read_allowed_only_in_read_or_write_roots(self):
        self.assertTrue(self.scope.allows(self.root / "ro" / "a.txt"))
        self.assertTrue(self.scope.allows(self.root / "rw" / "a.txt"))
        self.assertFalse(self.scope.allows(self.root / "other" / "a.txt"))

    def test_write_only_in_write_roots(self):
        self.assertTrue(self.scope.allows(self.root / "rw" / "a.txt", write=True))
        self.assertFalse(self.scope.allows(self.root / "ro" / "a.txt", write=True))

    def test_traversal_cannot_escape(self):
        self.assertFalse(self.scope.allows(self.root / "rw" / ".." / "escape.txt", write=True))

    def test_empty_scope_denies(self):
        self.assertFalse(FilesystemScope().allows(self.root / "x"))


class TestCommandPolicy(unittest.TestCase):
    def test_classification(self):
        p = CommandPolicy()
        self.assertEqual(p.classify(["cat", "/etc/hosts"]), RiskLevel.READ)
        self.assertEqual(p.classify(["cp", "a", "b"]), RiskLevel.WRITE)
        self.assertEqual(p.classify(["rm", "-rf", "/tmp/x"]), RiskLevel.DESTRUCTIVE)
        self.assertEqual(p.classify(["shutdown", "now"]), RiskLevel.DESTRUCTIVE)

    def test_sudo_classification_uses_wrapped_command_and_never_reads(self):
        p = CommandPolicy()
        # sudo elevates: a READ command becomes at least WRITE
        self.assertEqual(p.classify(["sudo", "cat", "/etc/shadow"]), RiskLevel.WRITE)
        # sudo options are skipped to find the real command
        self.assertEqual(p.classify(["sudo", "-S", "apt", "install", "nmap"]), RiskLevel.WRITE)
        self.assertEqual(p.classify(["sudo", "-u", "root", "cp", "a", "b"]), RiskLevel.WRITE)
        # a destructive wrapped command stays DESTRUCTIVE
        self.assertEqual(p.classify(["sudo", "rm", "-rf", "/x"]), RiskLevel.DESTRUCTIVE)
        # sudo with no command (e.g. `sudo -v`) is still privileged
        self.assertEqual(p.classify(["sudo", "-v"]), RiskLevel.WRITE)

    def test_allow_and_deny_lists(self):
        p = CommandPolicy(allowed_binaries={"cat", "ls"}, denied_binaries={"rm"})
        self.assertTrue(p.is_allowed(["cat", "x"]))
        self.assertFalse(p.is_allowed(["curl", "x"]))  # not on allowlist
        self.assertFalse(p.is_allowed(["rm", "x"]))     # denied


class TestFileOperations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scope = FilesystemScope(read_roots=[self.root], write_roots=[self.root])
        (self.root / "log.txt").write_text("alpha\nBETA secret\ngamma\n")

    def test_read_within_scope(self):
        r = ops.file_read(str(self.root / "log.txt"), self.scope)
        self.assertTrue(r["ok"])
        self.assertIn("alpha", r["content"])
        self.assertEqual(len(r["sha256"]), 64)

    def test_read_outside_scope_denied(self):
        r = ops.file_read(str(self.root / ".." / "outside.txt"), self.scope)
        self.assertFalse(r["ok"])
        self.assertIn("scope", r["error"])

    def test_write_and_edit(self):
        path = str(self.root / "note.txt")
        self.assertTrue(ops.file_write(path, "hello world", self.scope)["ok"])
        edit = ops.file_edit(path, "world", "there", self.scope)
        self.assertTrue(edit["ok"])
        self.assertEqual(edit["replacements"], 1)
        self.assertEqual(Path(path).read_text(), "hello there")

    def test_edit_missing_string_is_noop(self):
        path = str(self.root / "note.txt")
        ops.file_write(path, "abc", self.scope)
        self.assertFalse(ops.file_edit(path, "zzz", "y", self.scope)["ok"])

    def test_search(self):
        r = ops.file_search(str(self.root), "beta", self.scope)
        self.assertTrue(r["ok"])
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["matches"][0]["line"], 2)

    def test_list(self):
        r = ops.file_list(str(self.root), self.scope)
        self.assertTrue(r["ok"])
        self.assertIn("log.txt", [e["name"] for e in r["entries"]])

    def test_fetch_between_scoped_paths(self):
        dest = str(self.root / "copy" / "log.txt")
        r = ops.file_fetch(str(self.root / "log.txt"), dest, self.scope)
        self.assertTrue(r["ok"])
        self.assertTrue(Path(dest).is_file())


class TestCommandAndProcess(unittest.TestCase):
    def test_run_command_denied_binary(self):
        r = ops.run_command(["curl", "x"], CommandPolicy(allowed_binaries={"echo"}))
        self.assertFalse(r["ok"])

    @unittest.skipIf(sys.platform == "win32", "uses POSIX echo")
    def test_run_command_success_and_risk(self):
        r = ops.run_command(["echo", "hi"], CommandPolicy(allowed_binaries={"echo"}))
        self.assertTrue(r["ok"])
        self.assertEqual(r["risk"], "READ")
        self.assertIn("hi", r["stdout"])

    def test_process_list(self):
        r = ops.process_list(limit=5)
        self.assertTrue(r["ok"])
        self.assertGreater(r["total"], 0)


class TestHostSession(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "uses POSIX echo/pwd")
    def test_stateful_cd_and_transcript(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        Path(tmp.name, "sub").mkdir()
        scope = FilesystemScope(read_roots=[tmp.name])
        session = HostSession(CommandPolicy(allowed_binaries={"echo", "pwd"}), scope=scope, cwd=tmp.name)
        self.assertTrue(session.run(["cd", "sub"])["ok"])
        self.assertTrue(session.cwd.endswith("sub"))
        session.run(["echo", "hello"])
        self.assertEqual(session.summary()["commands_run"], 2)

    def test_cd_outside_scope_denied(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        scope = FilesystemScope(read_roots=[Path(tmp.name) / "in"])
        (Path(tmp.name) / "in").mkdir()
        session = HostSession(CommandPolicy(), scope=scope, cwd=str(Path(tmp.name) / "in"))
        self.assertFalse(session.run(["cd", ".."])["ok"])


class TestPermissionModes(unittest.TestCase):
    def test_mode_decisions(self):
        self.assertEqual(resolve_mode_decision(PermissionMode.PLAN, RiskLevel.READ), "deny")
        self.assertEqual(resolve_mode_decision(PermissionMode.ASK, RiskLevel.READ), "allow")
        self.assertEqual(resolve_mode_decision(PermissionMode.ASK, RiskLevel.WRITE), "approve")
        self.assertEqual(resolve_mode_decision(PermissionMode.AUTO, RiskLevel.WRITE), "allow")
        # DESTRUCTIVE is never auto-allowed
        self.assertEqual(resolve_mode_decision(PermissionMode.AUTO, RiskLevel.DESTRUCTIVE), "approve")


class TestHooks(unittest.TestCase):
    def test_pre_hook_veto_and_post_observe(self):
        reg = HookRegistry()
        seen = []
        reg.register_pre(lambda e: (e.capability != "file_write", "writes blocked"))
        reg.register_post(lambda e, outcome: seen.append(e.capability))

        allow, reason = reg.run_pre(HookEvent("pre", "file_write"))
        self.assertFalse(allow)
        self.assertIn("blocked", reason)

        allow, _ = reg.run_pre(HookEvent("pre", "file_read"))
        self.assertTrue(allow)
        reg.run_post(HookEvent("post", "file_read"), {"ok": True})
        self.assertEqual(seen, ["file_read"])

    def test_raising_pre_hook_fails_closed(self):
        reg = HookRegistry()
        reg.register_pre(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
        allow, reason = reg.run_pre(HookEvent("pre", "file_read"))
        self.assertFalse(allow)


class TestMcpDescriptors(unittest.TestCase):
    def test_every_capability_has_a_tool_descriptor(self):
        tools = {t["name"] for t in host_capability_tools()}
        self.assertIn("file_read", tools)
        self.assertIn("shell_command", tools)
        self.assertTrue(all(t["governed"] for t in host_capability_tools()))


if __name__ == "__main__":
    unittest.main()
