import asyncio
import json
import unittest

from decode.planner.dag import CompletionCriterion
from decode.runtime import ToolUseLoop
from decode.schema import TaskState
from decode.verification import ModelVerifier, Verifier

TOOLS = [{"name": "test_run", "description": "Run the test suite"}]


class TestVerifier(unittest.TestCase):
    def test_no_conditions_accepts(self):
        state = TaskState(objective="x")
        result = Verifier().verify(state)
        self.assertTrue(result.valid)

    def test_condition_on_last_success(self):
        state = TaskState(objective="x")
        state.completion_conditions.append(
            CompletionCriterion(kind="equals", field="last_success", expected=True)
        )
        state.record_action("test_run", {})
        state.record_observation("test_run", {"success": False, "summary": "1 failed"})
        self.assertFalse(Verifier().verify(state).valid)

        state.record_action("test_run", {})
        state.record_observation("test_run", {"success": True, "summary": "all passed"})
        self.assertTrue(Verifier().verify(state).valid)

    def test_condition_on_nested_observation_field(self):
        state = TaskState(objective="x")
        state.completion_conditions.append(
            CompletionCriterion(
                kind="equals", field="last_observation.exit_code", expected=0
            )
        )
        state.record_action("test_run", {})
        state.record_observation(
            "test_run", {"success": True, "data": {"exit_code": 1}}
        )
        self.assertFalse(Verifier().verify(state).valid)
        state.record_action("test_run", {})
        state.record_observation(
            "test_run", {"success": True, "data": {"exit_code": 0}}
        )
        self.assertTrue(Verifier().verify(state).valid)


class _ScriptedProvider:
    def __init__(self, replies):
        self._replies = list(replies)

    async def chat(self, messages):
        return self._replies.pop(0)


class _RaisingProvider:
    async def chat(self, messages):
        raise AssertionError("provider must not be called")


class TestModelVerifier(unittest.TestCase):
    def _state(self):
        return TaskState(objective="ship the feature")

    def test_model_accepts(self):
        provider = _ScriptedProvider([json.dumps({"valid": True, "reasons": []})])
        result = asyncio.run(ModelVerifier(provider).verify(self._state()))
        self.assertTrue(result.valid)

    def test_model_rejects_with_reasons(self):
        provider = _ScriptedProvider(
            [json.dumps({"valid": False, "reasons": ["tests fail"]})]
        )
        result = asyncio.run(ModelVerifier(provider).verify(self._state()))
        self.assertFalse(result.valid)
        self.assertIn("tests fail", result.reasons)

    def test_unparseable_reply_fails_open(self):
        provider = _ScriptedProvider(["I am not sure honestly"])
        result = asyncio.run(ModelVerifier(provider).verify(self._state()))
        self.assertTrue(result.valid)

    def test_hard_gate_runs_before_model(self):
        # a failing completion condition must short-circuit without calling the model
        state = self._state()
        state.completion_conditions.append(
            CompletionCriterion(kind="equals", field="last_success", expected=True)
        )
        state.record_action("test_run", {})
        state.record_observation("test_run", {"success": False})
        result = asyncio.run(ModelVerifier(_RaisingProvider()).verify(state))
        self.assertFalse(result.valid)

    def test_provider_error_fails_open(self):
        result = asyncio.run(ModelVerifier(_RaisingProvider()).verify(self._state()))
        self.assertTrue(result.valid)


class TestLoopReplanWithModelReviewer(unittest.TestCase):
    def test_reviewer_model_drives_replan(self):
        worker = _ScriptedProvider(
            [
                json.dumps({"message": "done (first attempt)"}),
                json.dumps({"tool": "test_run", "params": {}}),
                json.dumps({"message": "done for real"}),
            ]
        )
        reviewer = _ScriptedProvider(
            [
                json.dumps({"valid": False, "reasons": ["not yet"]}),
                json.dumps({"valid": True, "reasons": []}),
            ]
        )

        async def invoke(name, params):
            return {"success": True, "summary": "ok"}

        state = TaskState(objective="do the thing")
        loop = ToolUseLoop(
            worker,
            TOOLS,
            invoke,
            max_steps=6,
            task_state=state,
            verifier=ModelVerifier(reviewer),
            max_replans=2,
        )
        result = asyncio.run(loop.run("do the thing"))
        self.assertEqual(result["stopped"], "final")
        self.assertEqual(result["final"], "done for real")
        self.assertTrue(any(s["tool"] == "test_run" for s in result["steps"]))


class TestLoopReplan(unittest.TestCase):
    def test_finalization_blocked_until_condition_met(self):
        # Model tries to finish immediately (fail), then runs the tool, then finishes.
        provider = _ScriptedProvider(
            [
                json.dumps({"message": "done (prematurely)"}),
                json.dumps({"tool": "test_run", "params": {}}),
                json.dumps({"message": "tests pass now"}),
            ]
        )

        async def invoke(name, params):
            return {"success": True, "summary": "all passed"}

        state = TaskState(objective="make tests pass")
        state.completion_conditions.append(
            CompletionCriterion(kind="equals", field="last_success", expected=True)
        )
        events = []
        loop = ToolUseLoop(
            provider,
            TOOLS,
            invoke,
            max_steps=6,
            task_state=state,
            verifier=Verifier(),
            max_replans=2,
            on_step=events.append,
        )
        result = asyncio.run(loop.run("make tests pass"))

        self.assertEqual(result["stopped"], "final")
        self.assertEqual(result["final"], "tests pass now")
        # a verify event fired for the premature completion
        self.assertTrue(any(e.get("phase") == "verify" for e in events))
        # the tool ran during the replan
        self.assertTrue(any(s["tool"] == "test_run" for s in result["steps"]))

    def test_replan_is_bounded(self):
        # Model always tries to finish; condition never satisfied -> bounded, then accepts.
        provider = _ScriptedProvider([json.dumps({"message": "done"})] * 6)

        async def invoke(name, params):
            return {"success": False, "summary": "still failing"}

        state = TaskState(objective="impossible")
        state.completion_conditions.append(
            CompletionCriterion(kind="equals", field="last_success", expected=True)
        )
        loop = ToolUseLoop(
            provider,
            TOOLS,
            invoke,
            max_steps=6,
            task_state=state,
            verifier=Verifier(),
            max_replans=2,
        )
        result = asyncio.run(loop.run("impossible"))
        # after max_replans it accepts the final message rather than looping forever
        self.assertEqual(result["stopped"], "final")


if __name__ == "__main__":
    unittest.main()
