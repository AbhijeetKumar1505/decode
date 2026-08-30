import asyncio
import unittest

from decode.events import (
    AgentStatus,
    AgentThought,
    EventBus,
    FinalMessage,
    PlanUpdated,
    SessionStarted,
    TokensUpdated,
    ToolCompleted,
    ToolStarted,
)
from decode.tui.state import TUIStore


class TestEventBus(unittest.TestCase):
    def test_subscribe_emit_unsubscribe(self):
        seen = []
        bus = EventBus()
        unsub = bus.subscribe(seen.append)
        asyncio.run(bus.emit(AgentThought(text="hi")))
        self.assertEqual(len(seen), 1)
        unsub()
        asyncio.run(bus.emit(AgentThought(text="bye")))
        self.assertEqual(len(seen), 1)

    def test_async_subscriber(self):
        seen = []

        async def handler(event):
            seen.append(event)

        bus = EventBus()
        bus.subscribe(handler)
        asyncio.run(bus.emit(AgentStatus(status="thinking")))
        self.assertEqual(seen[0].status, "thinking")

    def test_broken_subscriber_does_not_break_emission(self):
        seen = []
        bus = EventBus()
        bus.subscribe(lambda e: 1 / 0)
        bus.subscribe(seen.append)
        asyncio.run(bus.emit(AgentThought(text="x")))
        self.assertEqual(len(seen), 1)

    def test_kind_property(self):
        self.assertEqual(ToolStarted(tool="git_diff").kind, "ToolStarted")


class _ScriptedProvider:
    def __init__(self, replies):
        self._replies = list(replies)
        self.session_tokens = 0

    async def chat(self, messages):
        self.session_tokens += 10
        return self._replies.pop(0)


class TestLoopEmitsEvents(unittest.TestCase):
    def test_loop_publishes_typed_events(self):
        import json

        from decode.runtime import ToolUseLoop

        provider = _ScriptedProvider([
            json.dumps({"thought": "run it", "tool": "process_list", "params": {}}),
            json.dumps({"message": "done"}),
        ])
        bus = EventBus()
        seen = []
        bus.subscribe(seen.append)

        async def invoke(name, params):
            return {"success": True, "summary": "ok", "data": {}}

        loop = ToolUseLoop(
            provider, [{"name": "process_list", "description": "list"}], invoke,
            max_steps=5, event_bus=bus,
        )
        asyncio.run(loop.run("goal"))
        kinds = {type(e).__name__ for e in seen}
        self.assertTrue(
            {"AgentStatus", "AgentThought", "ToolStarted", "ToolCompleted", "FinalMessage", "TokensUpdated"} <= kinds
        )


class TestTUIStore(unittest.TestCase):
    def test_folds_a_session(self):
        store = TUIStore()
        for event in [
            SessionStarted(goal="assess app", mode="security"),
            AgentStatus(status="thinking"),
            TokensUpdated(session_tokens=1200, step_tokens=200),
            AgentThought(text="I'll scan first"),
            ToolStarted(tool="shell_command", params={"command": "nmap x"}),
            ToolCompleted(tool="shell_command", success=True, summary="ports open", data={"exit_code": 0}),
            PlanUpdated(summary="TASK STATE\nObjective: assess app"),
            FinalMessage(message="done"),
            AgentStatus(status="complete"),
        ]:
            store.apply(event)
        view = store.view
        self.assertEqual(view.goal, "assess app")
        self.assertEqual(view.mode, "security")
        self.assertEqual(view.status, "complete")
        self.assertEqual(view.session_tokens, 1200)
        self.assertEqual(view.final, "done")
        kinds = [e.kind for e in view.entries]
        self.assertEqual(kinds, ["thought", "tool_call", "tool_result", "final"])
        self.assertIn("Objective: assess app", view.plan_summary)
        self.assertEqual(view.current_tool, "")

    def test_session_started_resets_view(self):
        store = TUIStore()
        store.apply(AgentThought(text="stale"))
        store.apply(SessionStarted(goal="new", mode="coding"))
        self.assertEqual(store.view.entries, [])
        self.assertEqual(store.view.goal, "new")

    def test_changed_regions(self):
        store = TUIStore()
        self.assertEqual(store.apply(AgentStatus(status="executing")), ["header"])
        self.assertEqual(store.apply(AgentThought(text="t")), ["session"])


if __name__ == "__main__":
    unittest.main()
