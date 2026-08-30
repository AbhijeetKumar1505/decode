import asyncio
import unittest

from decode.events import (
    AgentStatus,
    AgentThought,
    FinalMessage,
    SessionStarted,
    ToolCompleted,
    ToolStarted,
)
from decode.tui.console import DecodeConsole


class _FakeAgent:
    """Emits a scripted event sequence over the bus, like a real run_tool_loop."""

    async def run_tool_loop(self, goal, *, event_bus=None, **kwargs):
        await event_bus.emit(SessionStarted(goal=goal, mode="hybrid"))
        await event_bus.emit(AgentThought(text="I'll run a command"))
        await event_bus.emit(ToolStarted(tool="shell_command", params={"command": "echo hi"}))
        await event_bus.emit(ToolCompleted(
            tool="shell_command", success=True, summary="ran",
            data={"stdout": "hi", "exit_code": 0},
        ))
        await event_bus.emit(FinalMessage(message="all done"))
        await event_bus.emit(AgentStatus(status="complete"))
        return {"final": "all done"}


class _FakeRequest:
    request_id = "req-1"
    action = "shell_command"
    target = ""
    command = "rm -rf /tmp/x"

    class risk:
        value = "destructive"


class TestDecodeConsole(unittest.TestCase):
    def test_drive_runs_runtime_and_renders(self):
        async def scenario():
            app = DecodeConsole(_FakeAgent())
            async with app.run_test() as pilot:
                await app._drive("scan the app")
                await pilot.pause()
                view = app._store.view
                self.assertEqual(view.final, "all done")
                self.assertEqual(view.status, "complete")
                kinds = [e.kind for e in view.entries]
                self.assertIn("tool_result", kinds)
                self.assertIn("final", kinds)

        asyncio.run(scenario())

    def test_input_submit_schedules_a_worker(self):
        async def scenario():
            app = DecodeConsole(_FakeAgent())
            async with app.run_test() as pilot:
                from textual.widgets import Input

                app.query_one("#input", Input).value = "do it"
                await pilot.press("enter")
                await pilot.pause()
                # input is cleared on submit; the run was scheduled without error
                self.assertEqual(app.query_one("#input", Input).value, "")

        asyncio.run(scenario())

    def test_slash_mode_command_changes_permission_mode(self):
        async def scenario():
            from decode.hostcontrol import PermissionMode

            app = DecodeConsole(_FakeAgent())
            async with app.run_test() as pilot:
                from textual.widgets import Input

                app.query_one("#input", Input).value = "/mode auto"
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._perm_mode, PermissionMode.AUTO)

        asyncio.run(scenario())

    def test_auto_approve_returns_true_without_modal(self):
        async def scenario():
            app = DecodeConsole(_FakeAgent())
            async with app.run_test():
                app._auto_approve = True
                approved = await app._approve(_FakeRequest())
                self.assertTrue(approved)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
