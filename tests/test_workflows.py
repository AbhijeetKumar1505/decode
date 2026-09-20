import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from decode.persistence.manager import SessionManager
from decode.persistence.store import SessionStore
from decode.workflows import (
    EvidenceLink,
    StageResult,
    WorkflowRegistry,
    WorkflowRunner,
    WorkflowSpec,
    parse_workflow,
)


def _spec() -> WorkflowSpec:
    return WorkflowSpec.model_validate(
        {
            "name": "test-flow",
            "description": "test",
            "mode": "hybrid",
            "stages": [
                {
                    "id": "inspect",
                    "title": "Inspect",
                    "objective": "inspect",
                    "gate": {
                        "min_successful_actions": 1,
                        "require_evidence": True,
                    },
                },
                {
                    "id": "approve",
                    "title": "Approve",
                    "objective": "approve",
                    "depends_on": ["inspect"],
                    "execution": "human",
                    "gate": {"require_final": False},
                },
                {
                    "id": "finish",
                    "title": "Finish",
                    "objective": "finish",
                    "depends_on": ["approve"],
                },
            ],
        }
    )


class _Registry:
    def __init__(self, spec: WorkflowSpec) -> None:
        self.spec = spec

    def get(self, name: str) -> WorkflowSpec | None:
        return self.spec if name == self.spec.name else None


class WorkflowParsingTest(unittest.TestCase):
    def test_parse_workflow_from_playbook_frontmatter(self) -> None:
        text = """---
name: sample-flow
description: sample
workflow:
  mode: security
  stages:
    - id: inspect
      title: Inspect
      objective: Inspect safely
---
# Guidance
Keep evidence.
"""
        spec = parse_workflow(text, fallback_name="fallback")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.name, "sample-flow")
        self.assertEqual(spec.mode.value, "security")
        self.assertIn("Keep evidence", spec.guidance)

    def test_cycle_and_unknown_dependency_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown stages"):
            WorkflowSpec.model_validate(
                {
                    "name": "broken",
                    "description": "broken",
                    "stages": [
                        {
                            "id": "a",
                            "title": "A",
                            "objective": "A",
                            "depends_on": ["missing"],
                        }
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "cycle detected"):
            WorkflowSpec.model_validate(
                {
                    "name": "cycle",
                    "description": "cycle",
                    "stages": [
                        {
                            "id": "a",
                            "title": "A",
                            "objective": "A",
                            "depends_on": ["b"],
                        },
                        {
                            "id": "b",
                            "title": "B",
                            "objective": "B",
                            "depends_on": ["a"],
                        },
                    ],
                }
            )

    def test_packaged_workflows_cover_engineering_and_security_roles(self) -> None:
        names = {spec.name for spec in WorkflowRegistry().all()}
        self.assertTrue(
            {
                "engineering-delivery",
                "security-code-audit",
                "red-team-assessment",
                "blue-team-response",
                "purple-team-validation",
            }.issubset(names)
        )

    def test_environment_directory_overrides_packaged_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "flow.md").write_text(
                """---
name: engineering-delivery
description: overridden
workflow:
  version: custom
  stages:
    - id: inspect
      title: Inspect
      objective: Inspect
---
body
""",
                encoding="utf-8",
            )
            previous = os.environ.get("DECODE_PLAYBOOKS_DIR")
            os.environ["DECODE_PLAYBOOKS_DIR"] = directory
            try:
                spec = WorkflowRegistry().get("engineering-delivery")
            finally:
                if previous is None:
                    os.environ.pop("DECODE_PLAYBOOKS_DIR", None)
                else:
                    os.environ["DECODE_PLAYBOOKS_DIR"] = previous
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.version, "custom")


class WorkflowRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = SessionStore(db_path=Path(self.directory.name) / "workflow.db")
        self.runner = WorkflowRunner(
            registry=_Registry(_spec()),
            sessions=SessionManager(self.store),
        )

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    @staticmethod
    async def _executor(context: Any) -> StageResult:
        return StageResult(
            success=True,
            final=f"completed {context.stage.id}",
            summary="ok",
            successful_actions=1,
            evidence=[EvidenceLink(id=f"evidence-{context.stage.id}", sha256="abc")],
        )

    def test_run_pauses_at_human_gate_and_resumes(self) -> None:
        created = self.runner.start("test-flow", "test the workflow")
        paused = asyncio.run(self.runner.run(created.session_id, self._executor))
        self.assertEqual(paused.completed, ["inspect"])
        self.assertEqual(paused.needs_review, ["approve"])
        self.assertEqual(paused.status, "blocked")

        complete = asyncio.run(
            self.runner.run(
                created.session_id,
                self._executor,
                approve_stage="approve",
            )
        )
        self.assertEqual(complete.status, "complete")
        self.assertEqual(complete.failed, [])
        self.assertEqual(complete.completed, ["inspect", "approve", "finish"])
        state = self.runner.load_state(created.session_id)
        self.assertGreaterEqual(len(state.artifacts), 2)
        self.assertEqual(state.status.value, "complete")

    def test_gate_failure_stops_dependents(self) -> None:
        created = self.runner.start("test-flow", "test the workflow")

        async def no_evidence(_context: Any) -> StageResult:
            return StageResult(
                success=True,
                final="unsupported result",
                successful_actions=1,
            )

        report = asyncio.run(self.runner.run(created.session_id, no_evidence))
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.failed, ["inspect"])
        self.assertIn("protected evidence", report.message)
        self.assertNotIn("finish", report.completed)

    def test_target_required_fails_before_session_creation(self) -> None:
        required = _spec().model_copy(update={"target_required": True})
        runner = WorkflowRunner(
            registry=_Registry(required), sessions=SessionManager(self.store)
        )
        with self.assertRaisesRegex(ValueError, "explicit target"):
            runner.start("test-flow", "test")

    def test_interrupted_stage_is_fenced_for_review(self) -> None:
        created = self.runner.start("test-flow", "test")
        self.store.checkpoint_plan_node(
            created.session_id, "inspect", "running", increment_attempts=True
        )
        report = asyncio.run(self.runner.run(created.session_id, self._executor))
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.needs_review, ["inspect"])
        self.assertIn("interrupted", report.message)


if __name__ == "__main__":
    unittest.main()
