import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.audit import AuditLayer
from decode.feedback import FeedbackStore
from decode.hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from decode.logging_service import LoggingService


class _ScriptedProvider:
    def __init__(self, replies):
        self._replies = list(replies)

    async def chat(self, messages):
        return self._replies.pop(0)


class TestPersistentSession(unittest.TestCase):
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

    def test_cwd_persists_across_session_exec_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / "sub").mkdir()
            replies = [
                json.dumps({"tool": "session_open", "params": {"cwd": str(root)}}),
                json.dumps({"tool": "session_exec", "params": {"command": "cd sub"}}),
                json.dumps({"tool": "session_close", "params": {}}),
                json.dumps({"message": "done"}),
            ]
            agent = self._agent(root, replies)
            result = asyncio.run(agent.run_tool_loop(
                "use a persistent session",
                filesystem_scope=FilesystemScope(read_roots=[root], write_roots=[root]),
                command_policy=CommandPolicy(),
                permission_mode=PermissionMode.AUTO,
            ))

        tools = [s["tool"] for s in result["steps"]]
        self.assertEqual(tools, ["session_open", "session_exec", "session_close"])
        # every session step was governed and succeeded
        self.assertTrue(all(s["observation"]["success"] for s in result["steps"]))
        # the cd persisted: close reports the working directory ending in /sub
        close_obs = result["steps"][2]["observation"]
        self.assertTrue(str(close_obs["data"].get("cwd", "")).replace("\\", "/").endswith("/sub"))
        self.assertEqual(close_obs["data"].get("commands_run"), 1)

    def test_session_exec_runs_a_real_command(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            replies = [
                json.dumps({"tool": "session_exec", "params": {"command": "echo session-works"}}),
                json.dumps({"message": "done"}),
            ]
            agent = self._agent(root, replies)
            result = asyncio.run(agent.run_tool_loop(
                "echo in a session",
                filesystem_scope=FilesystemScope(read_roots=[root]),
                command_policy=CommandPolicy(),
                permission_mode=PermissionMode.AUTO,
            ))
        obs = result["steps"][0]["observation"]
        self.assertTrue(obs["success"])
        self.assertIn("session-works", obs["data"]["stdout"])


if __name__ == "__main__":
    unittest.main()
