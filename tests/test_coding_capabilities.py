import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.audit import AuditLayer
from decode.capabilities.coding import (
    build_coding_command,
    coding_tool_list,
    is_coding_capability,
    summarize_coding_result,
)
from decode.feedback import FeedbackStore
from decode.hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from decode.logging_service import LoggingService


class TestBuildCodingCommand(unittest.TestCase):
    def test_git_read_commands(self):
        self.assertEqual(build_coding_command("git_status", {}), (["git", "status", "--short"], None))
        self.assertEqual(build_coding_command("git_diff", {}), (["git", "diff"], None))
        self.assertEqual(
            build_coding_command("git_diff", {"path": "a.py", "staged": True}),
            (["git", "diff", "--staged", "--", "a.py"], None),
        )
        argv, _ = build_coding_command("git_log", {"limit": 5})
        self.assertEqual(argv, ["git", "log", "--oneline", "-n5"])

    def test_git_commit_requires_message(self):
        self.assertEqual(
            build_coding_command("git_commit", {"message": "fix"}),
            (["git", "commit", "-m", "fix"], None),
        )
        with self.assertRaises(ValueError):
            build_coding_command("git_commit", {})
        with self.assertRaises(ValueError):
            build_coding_command("git_commit", {"message": "line1\nline2"})

    def test_test_and_build_defaults_and_overrides(self):
        self.assertEqual(build_coding_command("test_run", {}), (["pytest", "-q"], None))
        self.assertEqual(build_coding_command("test_run", {"command": "pytest tests/x.py"})[0],
                         ["pytest", "tests/x.py"])
        self.assertEqual(build_coding_command("build_run", {}), (["make"], None))

    def test_patch_apply_uses_stdin(self):
        diff = "diff --git a/x b/x\n"
        argv, stdin = build_coding_command("patch_apply", {"diff": diff})
        self.assertEqual(argv, ["git", "apply", "-"])
        self.assertEqual(stdin, diff)
        with self.assertRaises(ValueError):
            build_coding_command("patch_apply", {})

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            build_coding_command("rm_rf_everything", {})

    def test_tool_list_and_membership(self):
        names = {t["name"] for t in coding_tool_list()}
        self.assertIn("git_diff", names)
        self.assertIn("test_run", names)
        self.assertTrue(is_coding_capability("git_commit"))
        self.assertFalse(is_coding_capability("shell_command"))


class TestSummarizeCodingResult(unittest.TestCase):
    def test_test_run_parsing(self):
        extra = summarize_coding_result("test_run", {"stdout": "3 passed, 1 failed", "exit_code": 1})
        self.assertEqual(extra["tests_passed"], 3)
        self.assertEqual(extra["tests_failed"], 1)
        self.assertFalse(extra["tests_ok"])

    def test_git_diff_files_changed(self):
        stdout = "diff --git a/x b/x\n...\ndiff --git a/y b/y\n"
        self.assertEqual(summarize_coding_result("git_diff", {"stdout": stdout})["files_changed"], 2)

    def test_git_status_entries(self):
        extra = summarize_coding_result("git_status", {"stdout": " M a\n?? b\n"})
        self.assertEqual(extra["changed_entries"], 2)

    def test_commit_ok(self):
        self.assertTrue(summarize_coding_result("git_commit", {"exit_code": 0})["ok"])


class _ScriptedProvider:
    def __init__(self, replies):
        self._replies = list(replies)

    async def chat(self, messages):
        return self._replies.pop(0)


class TestCodingCapabilityThroughLoop(unittest.TestCase):
    """A coding capability is translated to a governed shell_command in the loop."""

    def _agent(self, tmp, replies):
        import decode.universal_agent as ua

        with mock.patch.object(ua.Config, "validate", return_value=None), \
             mock.patch.object(ua, "create_provider", return_value=mock.Mock()), \
             mock.patch.object(ua, "SelfLearningMemory", return_value=mock.Mock()):
            agent = ua.UniversalAgent(provider="openrouter")
        agent.llm = _ScriptedProvider(replies)
        agent.audit = AuditLayer(base_path=tmp / "audit")
        agent.logging = LoggingService(base_path=tmp / "logs")
        agent.feedback = FeedbackStore(base_path=tmp / "feedback")
        agent.set_scope([], allow_all=True)
        return agent

    def test_git_status_is_exposed_and_translated(self):
        replies = [
            json.dumps({"tool": "git_status", "params": {}}),
            json.dumps({"message": "done"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            agent = self._agent(Path(d), replies)
            result = asyncio.run(agent.run_tool_loop(
                "check the repo status",
                filesystem_scope=FilesystemScope(read_roots=[Path.cwd()]),
                command_policy=CommandPolicy(),
                permission_mode=PermissionMode.AUTO,
            ))
        # the coding capability was in the surface (hybrid) and the loop invoked it
        self.assertEqual(result["steps"][0]["tool"], "git_status")
        self.assertIn("observation", result["steps"][0])


if __name__ == "__main__":
    unittest.main()
