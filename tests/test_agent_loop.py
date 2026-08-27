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
from decode.runtime import ToolUseLoop


class _ScriptedProvider:
    """Returns a queued reply per chat() call, ignoring the messages."""

    def __init__(self, replies):
        self._replies = list(replies)

    async def chat(self, messages):
        return self._replies.pop(0)


TOOLS = [
    {"name": "file_read", "description": "Read a file"},
    {"name": "process_list", "description": "List processes"},
]


class TestToolUseLoop(unittest.TestCase):
    def _run(self, loop, goal):
        return asyncio.run(loop.run(goal))

    def test_calls_tool_then_finishes(self):
        provider = _ScriptedProvider([
            json.dumps({"tool": "file_read", "params": {"path": "/etc/os-release"}}),
            json.dumps({"message": "The host runs Linux."}),
        ])
        calls = []

        async def invoke(name, params):
            calls.append((name, params))
            return {"success": True, "summary": "read ok", "content": "ID=debian"}

        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5)
        result = self._run(loop, "identify the OS")

        self.assertEqual(result["stopped"], "final")
        self.assertEqual(result["final"], "The host runs Linux.")
        self.assertEqual(calls, [("file_read", {"path": "/etc/os-release"})])
        self.assertEqual(len(result["steps"]), 1)

    def test_unknown_tool_is_reported_not_executed(self):
        provider = _ScriptedProvider([
            json.dumps({"tool": "delete_everything", "params": {}}),
            json.dumps({"message": "stopping"}),
        ])

        async def invoke(name, params):  # must NOT be called for an unknown tool
            raise AssertionError("invoke called for unknown tool")

        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5)
        result = self._run(loop, "do something")
        self.assertFalse(result["steps"][0]["observation"]["success"])
        self.assertIn("unknown tool", result["steps"][0]["observation"]["summary"])

    def test_step_budget_is_bounded(self):
        # always returns a tool call; the loop must stop at the budget
        provider = _ScriptedProvider([json.dumps({"tool": "process_list", "params": {}})] * 10)

        async def invoke(name, params):
            return {"success": True, "summary": "ok"}

        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=3)
        result = self._run(loop, "loop forever")
        self.assertEqual(result["stopped"], "budget")
        self.assertEqual(len(result["steps"]), 3)

    def test_first_person_thought_is_captured_and_streamed(self):
        provider = _ScriptedProvider([
            json.dumps({
                "thought": "I'll list the processes first.",
                "tool": "process_list",
                "params": {},
            }),
            json.dumps({"thought": "Done — reporting back.", "message": "ok"}),
        ])

        async def invoke(name, params):
            return {"success": True, "summary": "ok"}

        events = []
        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5, on_step=events.append)
        result = self._run(loop, "list processes")

        # the tool step records the thought
        self.assertEqual(result["steps"][0]["thought"], "I'll list the processes first.")
        # on_step saw a call, a result, and a final phase, carrying the thoughts
        phases = [e["phase"] for e in events]
        self.assertEqual(phases, ["call", "result", "final"])
        self.assertEqual(events[0]["thought"], "I'll list the processes first.")
        self.assertEqual(events[-1]["thought"], "Done — reporting back.")

    def test_non_json_reply_ends_loop_gracefully(self):
        provider = _ScriptedProvider(["I could not decide."])

        async def invoke(name, params):
            raise AssertionError("should not invoke")

        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5)
        result = self._run(loop, "goal")
        # parse_llm_response preserves raw text as message; no tool -> final
        self.assertEqual(result["stopped"], "final")
        self.assertIn("could not decide", result["final"])


class TestUniversalAgentLoopIntegration(unittest.TestCase):
    """End-to-end: the bare-prompt path discovers tools and drives them, governed."""

    def _build_agent(self, tmp, replies):
        import decode.universal_agent as ua

        with mock.patch.object(ua.Config, "validate", return_value=None), \
             mock.patch.object(ua, "create_provider", return_value=mock.Mock()), \
             mock.patch.object(ua, "SelfLearningMemory", return_value=mock.Mock()):
            agent = ua.UniversalAgent(provider="openrouter")
        agent.llm = _ScriptedProvider(replies)
        agent.audit = AuditLayer(base_path=tmp / "audit")
        agent.logging = LoggingService(base_path=tmp / "logs")
        agent.feedback = FeedbackStore(base_path=tmp / "feedback")
        # allow_all keeps the ScopePolicy out of the way; we test loop orchestration
        agent.set_scope([], allow_all=True)
        return agent

    def _loop(self, agent, goal):
        return asyncio.run(agent.run_tool_loop(
            goal,
            filesystem_scope=FilesystemScope(read_roots=[Path.cwd()]),
            command_policy=CommandPolicy(),
            permission_mode=PermissionMode.AUTO,
        ))

    def test_discovers_then_runs_a_tool_then_answers(self):
        replies = [
            json.dumps({"tool": "list_tools", "params": {"query": "echo"}}),
            json.dumps({"tool": "shell_command", "params": {"command": "echo loop-works"}}),
            json.dumps({"message": "done"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            agent = self._build_agent(Path(d), replies)
            result = self._loop(agent, "run echo")

        self.assertEqual(result["stopped"], "final")
        tools_used = [s["tool"] for s in result["steps"]]
        self.assertEqual(tools_used, ["list_tools", "shell_command"])
        self.assertTrue(all(s["observation"]["success"] for s in result["steps"]))
        self.assertIn("loop-works", result["steps"][1]["observation"]["data"]["stdout"])

    def test_missing_tool_is_reported_in_the_loop(self):
        replies = [
            json.dumps({"tool": "shell_command",
                        "params": {"argv": ["decode-nonexistent-xyz"]}}),
            json.dumps({"message": "that tool is not installed"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            agent = self._build_agent(Path(d), replies)
            result = self._loop(agent, "run a missing tool")

        obs = result["steps"][0]["observation"]
        self.assertFalse(obs["success"])
        self.assertIn("not found", obs["summary"].lower())


if __name__ == "__main__":
    unittest.main()
