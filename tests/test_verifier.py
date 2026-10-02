import asyncio
import json
import unittest

from decode.planner.dag import CompletionCriterion
from decode.runtime import ToolUseLoop
from decode.schema import TaskState
from decode.verification import ModelVerifier, Verifier

TOOLS = [{"name": "test_run", "description": "Run the test suite"}]


class TestVerifier(unittest.TestCase):
    def test_at_least_criterion_requires_numeric_minimum(self):
        criterion = CompletionCriterion(
            kind="at_least", field="successful_actions", expected=2
        )
        self.assertFalse(criterion.check({"successful_actions": True})[0])
        self.assertFalse(criterion.check({"successful_actions": float("nan")})[0])
        self.assertFalse(criterion.check({"successful_actions": 1})[0])
        self.assertTrue(criterion.check({"successful_actions": 2})[0])

    def test_successful_actions_and_protected_evidence_are_derived(self):
        state = TaskState(objective="inspect")
        state.completion_conditions = [
            CompletionCriterion(
                kind="at_least", field="successful_actions", expected=2
            ),
            CompletionCriterion(kind="at_least", field="evidence_count", expected=1),
        ]
        state.record_action("inspect", {})
        state.record_observation(
            "inspect", {"success": True, "evidence": {"id": "raw-only"}}
        )
        verdict = Verifier().verify(state)
        self.assertFalse(verdict.valid)
        self.assertEqual(len(verdict.failed_criteria), 2)
        state.record_action("inspect", {})
        state.record_observation(
            "inspect",
            {
                "success": True,
                "evidence": {"id": "protected", "sha256": "digest"},
            },
        )
        self.assertTrue(Verifier().verify(state).valid)

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

    def test_reviewer_rejection_after_budget_blocks_completion(self):
        worker = _ScriptedProvider([json.dumps({"message": "done"})])
        reviewer = _ScriptedProvider(
            [json.dumps({"valid": False, "reasons": ["evidence missing"]})]
        )

        async def invoke(name, params):
            raise AssertionError("no action should execute")

        state = TaskState(objective="verify evidence")
        loop = ToolUseLoop(
            worker,
            TOOLS,
            invoke,
            task_state=state,
            verifier=ModelVerifier(reviewer),
            max_replans=0,
        )

        result = asyncio.run(loop.run("verify evidence"))
        self.assertEqual(result["stopped"], "verification_failed")
        self.assertEqual(result["failed_criteria"], ["evidence missing"])
        self.assertEqual(state.status.value, "blocked")


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
        # Model always tries to finish; exhausted verification must not accept it.
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
        self.assertEqual(result["stopped"], "verification_failed")
        self.assertIn("completion not verified", result["final"])
        self.assertEqual(state.status.value, "blocked")
        self.assertTrue(result["failed_criteria"])

    def test_exhausted_verification_checkpoints_blocked_state(self):
        provider = _ScriptedProvider([json.dumps({"message": "done"})])

        async def invoke(name, params):
            raise AssertionError("no action should execute")

        state = TaskState(objective="verify")
        state.completion_conditions.append(
            CompletionCriterion(kind="equals", field="last_success", expected=True)
        )
        checkpoints = []
        events = []
        loop = ToolUseLoop(
            provider,
            TOOLS,
            invoke,
            task_state=state,
            verifier=Verifier(),
            max_replans=0,
            checkpoint=lambda current: checkpoints.append(current.status.value),
            on_step=events.append,
        )

        result = asyncio.run(loop.run("verify"))
        self.assertEqual(result["stopped"], "verification_failed")
        self.assertEqual(state.status.value, "blocked")
        self.assertEqual(checkpoints, ["investigating", "blocked"])
        self.assertEqual([event["phase"] for event in events], ["verify", "final"])
        self.assertFalse(events[-1]["verified"])


if __name__ == "__main__":
    unittest.main()
