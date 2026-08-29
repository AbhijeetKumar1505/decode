import tempfile
import unittest
from pathlib import Path

from decode.planner.dag import CompletionCriterion
from decode.persistence.store import SessionStore
from decode.schema import ScopeView, TaskMode, TaskState, TaskStatus
from decode.schema.store import TaskStateStore


class TestCompletionCriterion(unittest.TestCase):
    def test_present_pass_and_fail(self):
        crit = CompletionCriterion(kind="present", field="exit_code")
        self.assertEqual(crit.check({"exit_code": 0})[0], True)
        self.assertEqual(crit.check({"exit_code": ""})[0], False)
        self.assertEqual(crit.check({})[0], False)

    def test_equals(self):
        crit = CompletionCriterion(kind="equals", field="status", expected="ok")
        self.assertTrue(crit.check({"status": "ok"})[0])
        self.assertFalse(crit.check({"status": "bad"})[0])

    def test_nested_field_and_unsupported_kind(self):
        crit = CompletionCriterion(kind="present", field="a.b")
        self.assertTrue(crit.check({"a": {"b": 1}})[0])
        self.assertFalse(crit.check({"a": {}})[0])
        self.assertFalse(CompletionCriterion(kind="weird", field="x").check({"x": 1})[0])

    def test_non_required_always_passes(self):
        crit = CompletionCriterion(kind="present", field="x", required=False)
        self.assertTrue(crit.check({})[0])


class TestTaskState(unittest.TestCase):
    def _state(self):
        return TaskState(objective="add a function and test it", mode=TaskMode.CODING)

    def test_record_action_and_observation_increment(self):
        s = self._state()
        s.record_action("shell_command", {"command": "pytest"}, "run the tests")
        s.record_observation("shell_command", {"success": True, "summary": "3 passed"})
        self.assertEqual(len(s.actions), 1)
        self.assertEqual(len(s.observations), 1)
        self.assertEqual(s.actions[0].step, 1)
        self.assertTrue(s.observations[0].success)

    def test_findings_hypotheses_questions(self):
        s = self._state()
        s.add_hypothesis("auth boundary is weak", confidence=0.4)
        s.add_finding("SQLi in login", severity="high", evidence_ref="ev-1")
        s.add_question("which db backend?")
        self.assertEqual(len(s.hypotheses), 1)
        self.assertEqual(s.findings[0].severity, "high")
        self.assertIn("which db backend?", s.unresolved_questions)
        s.resolve_question("which db backend?")
        self.assertNotIn("which db backend?", s.unresolved_questions)

    def test_evaluate_completion(self):
        s = self._state()
        # no conditions -> never auto-complete
        ok, _failures = s.evaluate_completion({"exit_code": 0})
        self.assertFalse(ok)
        s.completion_conditions.append(CompletionCriterion(kind="equals", field="exit_code", expected=0))
        self.assertTrue(s.evaluate_completion({"exit_code": 0})[0])
        self.assertFalse(s.evaluate_completion({"exit_code": 1})[0])

    def test_observation_evidence_creates_linked_artifact(self):
        s = self._state()
        s.record_observation("shell_command", {
            "success": True, "summary": "ran", "data": {"exit_code": 0},
            "evidence": {"id": "ev-1", "sha256": "abc123"},
        })
        self.assertEqual(s.observations[0].evidence_ref, "ev-1")
        self.assertEqual(s.observations[0].evidence_hash, "abc123")
        self.assertEqual(len(s.artifacts), 1)
        art = s.artifacts[0]
        self.assertEqual(art.evidence_id, "ev-1")
        self.assertEqual(art.related_step, 1)
        self.assertEqual(art.action, "shell_command")

    def test_observation_without_evidence_makes_no_artifact(self):
        s = self._state()
        s.record_observation("process_list", {"success": True, "summary": "ok"})
        self.assertEqual(len(s.artifacts), 0)

    def test_mark_status(self):
        s = self._state()
        s.mark("complete")
        self.assertEqual(s.status, TaskStatus.COMPLETE)

    def test_render_compact_contains_key_sections(self):
        s = TaskState(
            objective="assess the lab",
            mode=TaskMode.SECURITY,
            scope=ScopeView(targets=["10.0.0.5"], allow_destructive=False),
        )
        s.record_action("shell_command", {"command": "nmap 10.0.0.5"}, "scan")
        s.record_observation("shell_command", {"success": True, "summary": "ports open"})
        s.add_finding("open ssh", severity="low")
        text = s.render_compact()
        self.assertIn("assess the lab", text)
        self.assertIn("security", text)
        self.assertIn("10.0.0.5", text)
        self.assertIn("open ssh", text)
        self.assertIn("shell_command", text)

    def test_persist_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(db_path=Path(d) / "t.db")
            try:
                ts_store = TaskStateStore(store)
                s = self._state()
                s.record_action("git_status", {}, "inspect")
                s.add_finding("missing test", severity="medium")
                ts_store.save(s)

                loaded = ts_store.load(s.session_id)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.objective, s.objective)
                self.assertEqual(len(loaded.actions), 1)
                self.assertEqual(loaded.findings[0].title, "missing test")
                self.assertIsNone(ts_store.load("no-such-session"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
