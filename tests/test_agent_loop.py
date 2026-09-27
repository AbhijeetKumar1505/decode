import asyncio
import hashlib
import json
import os
import sys
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
    {
        "name": "file_read",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {"name": "process_list", "description": "List processes"},
]


class TestToolUseLoop(unittest.TestCase):
    def _run(self, loop, goal):
        return asyncio.run(loop.run(goal))

    def test_calls_tool_then_finishes(self):
        provider = _ScriptedProvider(
            [
                json.dumps(
                    {"tool": "file_read", "params": {"path": "/etc/os-release"}}
                ),
                json.dumps({"message": "The host runs Linux."}),
            ]
        )
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
        provider = _ScriptedProvider(
            [
                json.dumps({"tool": "delete_everything", "params": {}}),
                json.dumps({"message": "stopping"}),
            ]
        )

        async def invoke(name, params):  # must NOT be called for an unknown tool
            raise AssertionError("invoke called for unknown tool")

        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5)
        result = self._run(loop, "do something")
        self.assertFalse(result["steps"][0]["observation"]["success"])
        self.assertIn("unknown tool", result["steps"][0]["observation"]["summary"])

    def test_unknown_tool_parameter_is_rejected_before_invoke(self):
        provider = _ScriptedProvider(
            [
                json.dumps(
                    {
                        "tool": "file_read",
                        "params": {"path": "/etc/os-release", "surprise": True},
                    }
                ),
                json.dumps({"message": "stopping"}),
            ]
        )

        async def invoke(name, params):
            raise AssertionError("invoke called with invalid parameters")

        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5)
        result = self._run(loop, "read a file")
        observation = result["steps"][0]["observation"]
        self.assertFalse(observation["success"])
        self.assertIn("unsupported tool parameters", observation["summary"])

    def test_non_object_tool_parameters_are_rejected_without_state_crash(self):
        from decode.schema import TaskState

        provider = _ScriptedProvider(
            [
                json.dumps({"tool": "file_read", "params": ["/etc/os-release"]}),
                json.dumps({"message": "stopping"}),
            ]
        )

        async def invoke(name, params):
            raise AssertionError("invoke called with invalid parameters")

        state = TaskState(objective="read a file")
        result = self._run(
            ToolUseLoop(provider, TOOLS, invoke, max_steps=5, task_state=state),
            "read a file",
        )

        observation = result["steps"][0]["observation"]
        self.assertFalse(observation["success"])
        self.assertIn("must be an object", observation["summary"])
        self.assertEqual(state.actions[0].params, {})

    def test_filtered_discovery_observation_keeps_late_matches_visible(self):
        seen = []

        class _Recorder(_ScriptedProvider):
            async def chat(self, messages):
                seen.append(list(messages))
                return await super().chat(messages)

        provider = _Recorder(
            [
                json.dumps({"tool": "list_tools", "params": {"query": "scanner"}}),
                json.dumps({"message": "done"}),
            ]
        )
        tools = [
            {"name": f"scanner-{index:04d}", "path": f"/tools/scanner-{index:04d}"}
            for index in range(250)
        ]

        async def invoke(name, params):
            return {"success": True, "summary": "found", "data": {"tools": tools}}

        discovery_tools = TOOLS + [
            {
                "name": "list_tools",
                "description": "List installed tools",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "additionalProperties": False,
                },
            }
        ]
        self._run(ToolUseLoop(provider, discovery_tools, invoke), "find a scanner")

        observation = seen[1][-1]["content"]
        self.assertIn("scanner-0249", observation)
        self.assertNotIn("observation_truncated", observation)

    def test_step_budget_is_bounded(self):
        # always returns a tool call; the loop must stop at the budget
        provider = _ScriptedProvider(
            [json.dumps({"tool": "process_list", "params": {}})] * 10
        )

        async def invoke(name, params):
            return {"success": True, "summary": "ok"}

        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=3)
        result = self._run(loop, "loop forever")
        self.assertEqual(result["stopped"], "budget")
        self.assertEqual(len(result["steps"]), 3)

    def test_first_person_thought_is_captured_and_streamed(self):
        provider = _ScriptedProvider(
            [
                json.dumps(
                    {
                        "thought": "I'll list the processes first.",
                        "tool": "process_list",
                        "params": {},
                    }
                ),
                json.dumps({"thought": "Done — reporting back.", "message": "ok"}),
            ]
        )

        async def invoke(name, params):
            return {"success": True, "summary": "ok"}

        events = []
        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5, on_step=events.append)
        result = self._run(loop, "list processes")

        # the tool step records the thought
        self.assertEqual(
            result["steps"][0]["thought"], "I'll list the processes first."
        )
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

    def test_xml_tool_call_reaches_governed_invoke_one_at_a_time(self):
        seen = []

        class _Recorder(_ScriptedProvider):
            async def chat(self, messages):
                seen.append(list(messages))
                return await super().chat(messages)

        provider = _Recorder(
            [
                """I'll inspect processes.
<tool_call>process_list</tool_call>
<tool_call>file_read
<arg_key>path</arg_key><arg_value>/etc/os-release</arg_value>
</tool_call>""",
                json.dumps({"message": "done"}),
            ]
        )
        calls = []

        async def invoke(name, params):
            calls.append((name, params))
            return {"success": True, "summary": "ok"}

        result = self._run(ToolUseLoop(provider, TOOLS, invoke), "inspect")

        self.assertEqual(result["stopped"], "final")
        self.assertEqual(calls, [("process_list", {})])
        self.assertIn("Only the first requested tool was executed", seen[1][-1]["content"])

    def test_uses_provider_assistant_history_message(self):
        seen = []
        details = [{"type": "reasoning.encrypted", "data": "opaque"}]

        class _ReasoningProvider(_ScriptedProvider):
            async def chat(self, messages):
                seen.append(list(messages))
                return await super().chat(messages)

            def assistant_message(self, content):
                return {
                    "role": "assistant",
                    "content": content,
                    "reasoning_details": details,
                }

        provider = _ReasoningProvider(
            [
                json.dumps({"tool": "process_list", "params": {}}),
                json.dumps({"message": "done"}),
            ]
        )

        async def invoke(name, params):
            return {"success": True, "summary": "ok"}

        self._run(ToolUseLoop(provider, TOOLS, invoke), "list processes")

        prior_assistant = next(
            message for message in seen[1] if message["role"] == "assistant"
        )
        self.assertIs(prior_assistant["reasoning_details"], details)


class TestToolUseLoopTaskState(unittest.TestCase):
    """The loop reads and writes the live task-state across steps."""

    def test_loop_records_actions_observations_and_completes(self):
        from decode.schema import TaskState, TaskStatus

        provider = _ScriptedProvider(
            [
                json.dumps(
                    {"thought": "list procs", "tool": "process_list", "params": {}}
                ),
                json.dumps({"message": "done"}),
            ]
        )

        async def invoke(name, params):
            return {"success": True, "summary": "ok", "data": {"n": 3}}

        state = TaskState(objective="list processes")
        loop = ToolUseLoop(provider, TOOLS, invoke, max_steps=5, task_state=state)
        result = asyncio.run(loop.run("list processes"))

        self.assertEqual(result["stopped"], "final")
        self.assertEqual(len(state.actions), 1)
        self.assertEqual(state.actions[0].tool, "process_list")
        self.assertEqual(len(state.observations), 1)
        self.assertTrue(state.observations[0].success)
        self.assertEqual(state.status, TaskStatus.COMPLETE)
        # the compact state is surfaced back to callers
        self.assertIn("list processes", result["state_summary"])

    def test_compact_state_is_sent_to_the_model_each_turn(self):
        from decode.schema import TaskState

        seen = []

        class _Recorder:
            async def chat(self, messages):
                seen.append([m["role"] for m in messages])
                return json.dumps({"message": "ok"})

        state = TaskState(objective="inspect the repo")
        loop = ToolUseLoop(
            _Recorder(), TOOLS, lambda n, p: None, max_steps=2, task_state=state
        )
        asyncio.run(loop.run("inspect the repo"))
        # a transient system state-message is appended for the model call
        self.assertGreaterEqual(seen[0].count("system"), 2)

    def test_checkpoint_failure_prevents_execution(self):
        from decode.schema import TaskState

        state = TaskState(objective="inspect")
        calls = []

        async def invoke(name, params):
            calls.append(name)
            return {"success": True, "summary": "ok"}

        def checkpoint(current):
            if current.actions:
                raise OSError("checkpoint unavailable")

        loop = ToolUseLoop(
            _ScriptedProvider([json.dumps({"tool": "process_list", "params": {}})]),
            TOOLS,
            invoke,
            task_state=state,
            checkpoint=checkpoint,
        )
        with self.assertRaisesRegex(OSError, "checkpoint unavailable"):
            asyncio.run(loop.run("inspect"))
        self.assertEqual(calls, [])

    def test_observation_checkpoint_failure_stops_next_action(self):
        from decode.schema import TaskState

        state = TaskState(objective="inspect")
        calls = []

        async def invoke(name, params):
            calls.append(name)
            return {"success": True, "summary": "ok"}

        def checkpoint(current):
            if current.observations:
                raise OSError("checkpoint unavailable")

        replies = [json.dumps({"tool": "process_list", "params": {}})] * 2
        loop = ToolUseLoop(
            _ScriptedProvider(replies), TOOLS, invoke, task_state=state,
            checkpoint=checkpoint,
        )
        with self.assertRaisesRegex(OSError, "checkpoint unavailable"):
            asyncio.run(loop.run("inspect"))
        self.assertEqual(calls, ["process_list"])


class TestUniversalAgentLoopIntegration(unittest.TestCase):
    """End-to-end: the bare-prompt path discovers tools and drives them, governed."""

    def _build_agent(self, tmp, replies):
        import decode.universal_agent as ua

        with (
            mock.patch.object(ua.Config, "validate", return_value=None),
            mock.patch.object(ua, "create_provider", return_value=mock.Mock()),
            mock.patch.object(ua, "SelfLearningMemory", return_value=mock.Mock()),
        ):
            agent = ua.UniversalAgent(provider="openrouter")
        agent.llm = _ScriptedProvider(replies)
        agent.audit = AuditLayer(base_path=tmp / "audit")
        agent.logging = LoggingService(base_path=tmp / "logs")
        agent.feedback = FeedbackStore(base_path=tmp / "feedback")
        # allow_all keeps the ScopePolicy out of the way; we test loop orchestration
        agent.set_scope([], allow_all=True)
        return agent

    def _loop(self, agent, goal):
        return asyncio.run(
            agent.run_tool_loop(
                goal,
                filesystem_scope=FilesystemScope(read_roots=[Path.cwd()]),
                command_policy=CommandPolicy(),
                permission_mode=PermissionMode.AUTO,
            )
        )

    def test_discovers_then_runs_a_tool_then_answers(self):
        executable = Path(sys.executable).name
        replies = [
            json.dumps({"tool": "list_tools", "params": {"query": executable}}),
            json.dumps(
                {
                    "tool": "shell_command",
                    "params": {
                        "argv": [sys.executable, "-c", "print('loop-works')"]
                    },
                }
            ),
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

    def test_evidence_is_linked_as_a_task_artifact(self):
        replies = [
            json.dumps(
                {
                    "tool": "shell_command",
                    "params": {
                        "argv": [
                            sys.executable,
                            "-c",
                            "print('artifact-test')",
                        ]
                    },
                }
            ),
            json.dumps({"message": "done"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            agent = self._build_agent(Path(d), replies)
            result = self._loop(agent, "run echo")
        # the captured evidence flowed into the task state as a linked artifact
        self.assertIn("Artifacts:", result["state_summary"])

    def _governed_checkpoint_conformance(self, executor, command):
        from decode.persistence.store import SessionStore
        from decode.schema import TaskStatus
        from decode.schema.store import TaskStateStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(db_path=root / "decode.db")
            try:
                sid = store.create_session(goal="provider conformance")
                states = TaskStateStore(store)
                replies = [
                    json.dumps({"tool": "list_tools", "params": {"query": "printf"}}),
                    json.dumps({"tool": "shell_command", "params": {"argv": command}}),
                ]
                agent = self._build_agent(root, replies)
                agent.execution_provider = executor

                async def approve(_request):
                    return True

                kwargs = {
                    "filesystem_scope": FilesystemScope(read_roots=[Path.cwd()]),
                    "command_policy": CommandPolicy(),
                    "permission_mode": PermissionMode.ASK,
                    "approval_callback": approve,
                    "session_id": sid,
                    "checkpoint": states.save,
                }
                first = asyncio.run(
                    agent.run_tool_loop("provider conformance", max_steps=2, **kwargs)
                )
                self.assertEqual(first["stopped"], "budget")
                self.assertEqual(
                    [step["tool"] for step in first["steps"]],
                    ["list_tools", "shell_command"],
                )
                self.assertTrue(
                    all(step["observation"]["success"] for step in first["steps"]),
                    [step["observation"]["summary"][:200] for step in first["steps"]],
                )
                self.assertIn("decode-phase1-ok", first["steps"][1]["observation"]["data"]["stdout"])
                checkpoint = states.load(sid)
                self.assertEqual(len(checkpoint.actions), 2)
                self.assertEqual(len(checkpoint.observations), 2)
                self.assertEqual(checkpoint.status, TaskStatus.INVESTIGATING)
                self.assertEqual(checkpoint.environment["executor"], executor.name)
                self.assertTrue(checkpoint.artifacts)
                evidence = checkpoint.artifacts[-1]
                evidence_path = agent._coordinator._evidence.base_path / f"{evidence.evidence_id}.evidence"
                self.assertTrue(evidence_path.is_file())
                self.assertEqual(
                    hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                    evidence.evidence_hash,
                )
                self.assertTrue(agent.logging.get_logs(tool_filter="shell_command"))
                self.assertTrue(agent.audit.query(event_type="tool_execution"))
                self.assertTrue(agent.feedback.get_execution_feedback("shell_command"))

                agent.llm = _ScriptedProvider([json.dumps({"message": "done"})])
                second = asyncio.run(
                    agent.run_tool_loop(
                        "provider conformance", resume_state=checkpoint, **kwargs
                    )
                )
                self.assertEqual(second["stopped"], "final")
                self.assertEqual(len(states.load(sid).actions), 2)
                self.assertEqual(states.load(sid).status, TaskStatus.COMPLETE)
            finally:
                store.close()

    def test_local_governed_checkpoint_conformance(self):
        from decode.execution import LocalExecutor

        self._governed_checkpoint_conformance(
            LocalExecutor(), [sys.executable, "-c", "print('decode-phase1-ok')"]
        )

    def test_resume_rejects_unresolved_action_and_session_mismatch(self):
        from decode.schema import TaskState

        with tempfile.TemporaryDirectory() as directory:
            agent = self._build_agent(Path(directory), [])
            state = TaskState(session_id="session-1", objective="inspect")
            state.record_action("shell_command", {"argv": ["echo", "once"]})
            for sid in ("session-1", "session-2"):
                with self.assertRaisesRegex(ValueError, "checkpoint"):
                    asyncio.run(
                        agent.run_tool_loop(
                            "inspect", session_id=sid, resume_state=state
                        )
                    )

    @unittest.skipUnless(
        sys.platform == "win32" and os.environ.get("DECODE_RUN_WSL_CONFORMANCE") == "1",
        "requires explicit Kali WSL conformance opt-in",
    )
    def test_kali_wsl_governed_checkpoint_conformance(self):
        from decode.execution import WSLExecutor

        self._governed_checkpoint_conformance(
            WSLExecutor(distro="kali-linux"),
            ["/usr/bin/printf", "decode-phase1-ok"],
        )

    @unittest.skipUnless(
        os.environ.get("DECODE_GOVERNED_DOCKER_IMAGE", ""),
        "requires a cached GNU-compatible Docker image",
    )
    def test_docker_governed_checkpoint_conformance(self):
        from decode.execution import DockerExecutor

        self._governed_checkpoint_conformance(
            DockerExecutor(image=os.environ["DECODE_GOVERNED_DOCKER_IMAGE"], network="none"),
            ["/usr/bin/printf", "decode-phase1-ok"],
        )

    def test_mcp_tool_is_exposed_and_routed_through_the_coordinator(self):
        from decode.execution.mcp import MCPExecutor
        from decode.extensions.mcp_manager import MCPToolDescriptor

        class _Client:
            async def call_tool(self, name, arguments):
                return {"found": 1, "tool": name, "args": arguments}

            async def check(self):
                return True

        class _FakeMCPManager:
            def __init__(self):
                self._client = _Client()

            async def available_tools(self):
                return [
                    MCPToolDescriptor(
                        server="db",
                        name="db.find",
                        tool="find",
                        description="find docs",
                        risk="read",
                    )
                ]

            def executor_for(self, server):
                return MCPExecutor(server=server, client=self._client)

        replies = [
            json.dumps({"tool": "db.find", "params": {"q": 1}}),
            json.dumps({"message": "done"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            agent = self._build_agent(Path(d), replies)
            result = asyncio.run(
                agent.run_tool_loop(
                    "query the database",
                    filesystem_scope=FilesystemScope(read_roots=[Path.cwd()]),
                    command_policy=CommandPolicy(),
                    permission_mode=PermissionMode.AUTO,
                    mcp_manager=_FakeMCPManager(),
                )
            )
        self.assertEqual(result["steps"][0]["tool"], "db.find")
        obs = result["steps"][0]["observation"]
        self.assertTrue(obs["success"])
        self.assertIn("found", obs["data"]["stdout"])

    def test_mcp_required_url_is_checked_against_engagement_scope(self):
        from decode.execution.mcp import MCPExecutor
        from decode.extensions.mcp_manager import MCPToolDescriptor

        class _Client:
            def __init__(self):
                self.called = False

            async def call_tool(self, name, arguments):
                self.called = True
                return {"opened": arguments["url"]}

            async def check(self):
                return True

        client = _Client()

        class _FakeMCPManager:
            async def available_tools(self):
                return [
                    MCPToolDescriptor(
                        server="browser",
                        name="browser.open",
                        tool="open",
                        description="Open a URL",
                        risk="read",
                        input_schema={
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                            "required": ["url"],
                            "additionalProperties": False,
                        },
                    )
                ]

            def executor_for(self, server):
                return MCPExecutor(server=server, client=client)

        replies = [
            json.dumps(
                {
                    "tool": "browser.open",
                    "params": {"url": "https://outside.example.test"},
                }
            ),
            json.dumps({"message": "denied"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            agent = self._build_agent(Path(d), replies)
            agent.set_scope(["allowed.example.test"], allow_all=False)
            result = asyncio.run(
                agent.run_tool_loop(
                    "open the URL",
                    filesystem_scope=FilesystemScope(read_roots=[Path.cwd()]),
                    command_policy=CommandPolicy(),
                    permission_mode=PermissionMode.AUTO,
                    mcp_manager=_FakeMCPManager(),
                )
            )

        observation = result["steps"][0]["observation"]
        self.assertFalse(observation["success"])
        self.assertIn("out of engagement scope", observation["summary"])
        self.assertFalse(client.called)

    def test_missing_tool_is_reported_in_the_loop(self):
        replies = [
            json.dumps(
                {
                    "tool": "shell_command",
                    "params": {"argv": ["decode-nonexistent-xyz"]},
                }
            ),
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


def test_offline_tool_regression_runs_the_real_loop() -> None:
    from decode.evaluation import ToolEvalCase, evaluate_tool_calls

    case = ToolEvalCase(
        id="read",
        prompt="read the lab description",
        expected_calls=[
            {"name": "file_read", "arguments": {"path": "/lab/description"}},
        ],
    )

    def generate(prompt: str) -> list[dict]:
        calls = []

        async def observe(name: str, params: dict) -> dict:
            calls.append({"name": name, "arguments": params})
            return {"success": True, "summary": "synthetic lab data"}

        provider = _ScriptedProvider(
            [
                json.dumps(
                    {"tool": "file_read", "params": {"path": "/lab/description"}}
                ),
                json.dumps({"message": "done"}),
            ]
        )
        result = asyncio.run(ToolUseLoop(provider, TOOLS, observe).run(prompt))
        assert result["stopped"] == "final"
        return calls

    assert evaluate_tool_calls([case], generate).passed
