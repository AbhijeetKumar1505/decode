import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from decode.audit import AuditLayer
from decode.execution import LocalExecutor
from decode.feedback import FeedbackStore
from decode.hostcontrol import PermissionMode
from decode.logging_service import LoggingService
from decode.persistence.evidence import EvidenceReference
from decode.persistence.manager import SessionManager
from decode.persistence.store import SessionStore
from decode.runtime.coordinator import (
    CoordinatedResult,
    ExecutionErrorCategory,
    ExecutionStatus,
)
from decode.schema import (
    ActiveEscalation,
    ActiveEscalationKind,
    ActiveNodeResult,
    ActiveObservation,
    TaskState,
)
from decode.universal_agent import UniversalAgent
from decode.workflows import (
    BoundStageContext,
    EvidenceLink,
    GovernedReadStageExecutor,
    ReadStageAction,
    StageResult,
    WorkflowGate,
    WorkflowRegistry,
    WorkflowRunner,
    WorkflowSpec,
    WorkflowStageContext,
    parse_workflow,
)
from decode.workflows.agent_executor import (
    ActiveStageRuntime,
    GovernedAgentStageExecutor,
)
from decode.workflows.models import file_path_fingerprint


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
    def test_stage_outcome_cannot_contradict_success(self) -> None:
        with self.assertRaises(ValidationError):
            StageResult(success=True, outcome="needs_replan")

    def test_active_observation_rejects_untrusted_signals_and_unpaired_evidence(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            ActiveObservation(
                request_id="one",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                evidence_id="artifact",
            )
        with self.assertRaises(ValidationError):
            ActiveObservation(
                request_id="one",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                signals={"file_content": "sensitive"},
            )
        with self.assertRaises(ValidationError):
            ActiveObservation(
                request_id="one",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                signals={"file_size_bytes": "-1"},
            )
        with self.assertRaises(ValidationError):
            ActiveObservation(
                request_id="one",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                evidence_id="x" * 129,
                evidence_hash="a" * 64,
            )

    def test_file_metadata_must_come_from_one_evidence_linked_read(self) -> None:
        gate = WorkflowGate(expected_file_sha256="a" * 64, expected_file_size_bytes=12)
        result = StageResult(success=True, final="done", successful_actions=2)
        reads = [
            ActiveObservation(
                request_id="digest",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                evidence_id="one",
                evidence_hash="b" * 64,
                signals={"file_sha256": "a" * 64},
            ),
            ActiveObservation(
                request_id="size",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                evidence_id="two",
                evidence_hash="c" * 64,
                signals={"file_size_bytes": "12"},
            ),
        ]
        valid, failures = gate.check(result, reads)
        self.assertFalse(valid)
        self.assertIn(
            "governed file digest and size were not observed together", failures
        )
        with self.assertRaises(ValidationError):
            WorkflowGate(expected_file_size_bytes=-1)
        with self.assertRaises(ValidationError):
            WorkflowGate(expected_file_size_bytes=True)

    def test_artifact_path_requires_digest_and_same_evidence_linked_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deliverable.txt"
            other = Path(directory) / "other.txt"
            with self.assertRaises(ValidationError):
                WorkflowGate(expected_file_path=str(path))
            with self.assertRaises(ValidationError):
                WorkflowGate(
                    expected_file_path="relative.txt", expected_file_sha256="a" * 64
                )
            with self.assertRaises(ValidationError):
                WorkflowGate(
                    expected_file_path=str(path) + "\x00",
                    expected_file_sha256="a" * 64,
                )
            gate = WorkflowGate(
                expected_file_path=str(path), expected_file_sha256="a" * 64
            )
            result = StageResult(success=True, final="done", successful_actions=2)
            observations = [
                ActiveObservation(
                    request_id="path",
                    capability="file_read",
                    provider="internal",
                    status="success",
                    success=True,
                    evidence_id="one",
                    evidence_hash="b" * 64,
                    signals={"file_path_sha256": file_path_fingerprint(str(path))},
                ),
                ActiveObservation(
                    request_id="digest",
                    capability="file_read",
                    provider="internal",
                    status="success",
                    success=True,
                    evidence_id="two",
                    evidence_hash="c" * 64,
                    signals={
                        "file_path_sha256": file_path_fingerprint(str(other)),
                        "file_sha256": "a" * 64,
                    },
                ),
            ]
            valid, failures = gate.check(result, observations)
            self.assertFalse(valid)
            self.assertIn(
                "governed file artifact criteria were not observed together", failures
            )
            unprotected = ActiveObservation(
                request_id="unprotected",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                signals={
                    "file_path_sha256": file_path_fingerprint(str(path)),
                    "file_sha256": "a" * 64,
                },
            )
            valid, failures = gate.check(result, [unprotected])
            self.assertFalse(valid)
            self.assertIn("governed file path", failures[0])

    def test_incomplete_active_result_requires_linked_typed_escalation(self) -> None:
        observation = ActiveObservation(
            request_id="read-one",
            capability="file_read",
            provider="internal",
            status="timeout",
            error_category="timeout",
        )
        fields: dict[str, Any] = {
            "session_id": "session",
            "node_id": "inspect",
            "workflow_fingerprint": "a" * 64,
            "node_fingerprint": "b" * 64,
            "outcome": "blocked",
            "attempts": 1,
            "observations": (observation,),
        }
        with self.assertRaises(ValidationError):
            ActiveNodeResult(**fields)
        with self.assertRaises(ValidationError):
            ActiveNodeResult(
                **fields,
                escalation=ActiveEscalation(
                    kind=ActiveEscalationKind.TIMEOUT, request_id="other"
                ),
            )

    def test_completed_dependency_context_is_bounded_to_verified_evidence(
        self,
    ) -> None:
        spec = WorkflowSpec.model_validate(
            {
                "name": "context-flow",
                "description": "context fixture",
                "stages": [
                    {"id": "inspect", "title": "Inspect", "objective": "inspect"},
                    {
                        "id": "review",
                        "title": "Review",
                        "objective": "review",
                        "depends_on": ["inspect"],
                    },
                ],
            }
        )
        state = TaskState(
            session_id="session",
            objective="goal",
            plan=spec.to_plan("goal"),
            environment={
                "workflow": spec.name,
                "workflow_version": spec.version,
                "workflow_fingerprint": spec.fingerprint(),
                "target": "",
            },
        )
        state.plan.mark("inspect", "success")
        observations = tuple(
            ActiveObservation(
                request_id=f"request-{index}",
                capability="file_read",
                provider="internal",
                status="success",
                success=True,
                evidence_id=f"evidence-{index}",
                evidence_hash="a" * 64,
            )
            for index in range(9)
        )
        state.active_nodes["inspect"] = ActiveNodeResult(
            session_id=state.session_id,
            node_id="inspect",
            workflow_fingerprint=spec.fingerprint(),
            node_fingerprint=state.plan.nodes["inspect"].material_fingerprint(),
            outcome="completed",
            gate_passed=True,
            attempts=9,
            observations=observations,
        )
        context = WorkflowStageContext(
            session_id="session",
            workflow_name=spec.name,
            workflow_version=spec.version,
            goal="goal",
            stage=spec.stage("review"),
        )

        bound = BoundStageContext.from_task(state, context)
        runtime = ActiveStageRuntime(state, context)
        self.assertEqual(len(bound.prior_evidence), 8)
        self.assertEqual(bound.prior_evidence[0].evidence_id, "evidence-0")
        self.assertEqual(bound.prior_evidence[-1].evidence_id, "evidence-7")
        state.plan.nodes["inspect"].params["objective"] = "changed dependency"
        self.assertFalse(runtime.unchanged())
        state.plan.nodes["inspect"].params["objective"] = "inspect"
        self.assertTrue(runtime.unchanged())
        state.active_nodes["inspect"] = state.active_nodes["inspect"].model_copy(
            update={"node_fingerprint": "0" * 64}
        )
        self.assertFalse(runtime.unchanged())
        self.assertEqual(BoundStageContext.from_task(state, context).prior_evidence, ())

    def test_stage_context_rejects_unfinished_dependencies(self) -> None:
        spec = _spec()
        state = TaskState(
            session_id="session",
            objective="goal",
            plan=spec.to_plan("goal"),
            environment={
                "workflow": spec.name,
                "workflow_version": spec.version,
                "workflow_fingerprint": spec.fingerprint(),
                "target": "",
            },
        )
        context = WorkflowStageContext(
            session_id="session",
            workflow_name=spec.name,
            workflow_version=spec.version,
            goal="goal",
            stage=spec.stage("finish"),
        )
        with self.assertRaisesRegex(ValueError, "durable task plan"):
            BoundStageContext.from_task(state, context)

    def test_active_completion_requires_protected_evidence_even_without_declared_gate(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValidationError, "protected observation"):
            ActiveNodeResult(
                session_id="session",
                node_id="inspect",
                workflow_fingerprint="a" * 64,
                node_fingerprint="b" * 64,
                outcome="completed",
                gate_passed=True,
                attempts=1,
                observations=(
                    ActiveObservation(
                        request_id="unprotected",
                        capability="file_read",
                        provider="internal",
                        status="success",
                        success=True,
                    ),
                ),
            )

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

    def test_evidence_without_hash_fails_gate(self) -> None:
        gate = _spec().stage("inspect").gate
        valid, failures = gate.check(
            StageResult(
                success=True,
                final="done",
                successful_actions=1,
                evidence=[EvidenceLink(id="unprotected")],
            )
        )
        self.assertFalse(valid)
        self.assertIn("stage produced no protected evidence reference", failures)

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

    def test_exhausted_verification_pauses_stage_and_dependents(self) -> None:
        created = self.runner.start("test-flow", "test")

        async def unverified(_context: Any) -> StageResult:
            return StageResult(
                success=False,
                outcome="needs_replan",
                final="completion not verified",
                error="completion not verified",
                failed_criteria=["evidence_count is below the required minimum"],
            )

        report = asyncio.run(self.runner.run(created.session_id, unverified))
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.needs_review, ["inspect"])
        self.assertEqual(report.failed, [])
        self.assertNotIn("finish", report.completed)
        state = self.runner.load_state(created.session_id)
        self.assertEqual(state.plan.nodes["inspect"].status, "needs_review")
        self.assertEqual(state.observations[-1].summary, "failure")


class GovernedStageExecutorTest(unittest.TestCase):
    class FakeAgent:
        def set_scope(
            self, targets: list[str], *, allow_destructive: bool = False
        ) -> None:
            self._scope_entries = targets.copy()

    @staticmethod
    def _state() -> TaskState:
        return TaskState(
            session_id="test",
            objective="inspect",
            plan=_spec().to_plan("inspect"),
            environment={
                "workflow": "test-flow",
                "workflow_version": "1",
                "workflow_fingerprint": _spec().fingerprint(),
                "target": "",
            },
        )

    def test_stage_passes_declared_criteria_and_returns_typed_outcome(self) -> None:
        executor = GovernedAgentStageExecutor(self._state())

        class FakeAgent(self.FakeAgent):
            _last_task_state = TaskState(objective="inspect")

            async def run_tool_loop(
                self, _prompt: str, **kwargs: Any
            ) -> dict[str, Any]:
                self.kwargs = kwargs
                return {
                    "stopped": "verification_failed",
                    "final": "completion not verified",
                    "failed_criteria": ["evidence_count is below the required minimum"],
                    "steps": [],
                }

        fake = FakeAgent()
        executor._agent = fake
        stage = _spec().stage("inspect")
        context = WorkflowStageContext(
            session_id="test",
            workflow_name="test-flow",
            workflow_version="1",
            goal="inspect",
            stage=stage,
        )
        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "needs_replan")
        self.assertFalse(result.success)
        self.assertEqual(
            result.failed_criteria, ["evidence_count is below the required minimum"]
        )
        self.assertEqual(
            [
                (item.kind, item.field, item.expected)
                for item in fake.kwargs["completion_conditions"]
            ],
            [
                ("at_least", "successful_actions", 1),
                ("at_least", "evidence_count", 1),
            ],
        )

    def test_uncaptured_step_and_artifact_cannot_satisfy_governed_gate(self) -> None:
        executor = GovernedAgentStageExecutor(self._state())

        class FakeAgent(self.FakeAgent):
            _last_task_state = TaskState(objective="inspect")

            async def run_tool_loop(
                self, _prompt: str, **_kwargs: Any
            ) -> dict[str, Any]:
                return {
                    "stopped": "final",
                    "final": "claimed completion",
                    "steps": [{"observation": {"success": True}}],
                }

        fake = FakeAgent()
        fake._last_task_state.add_artifact(
            evidence_id="claimed", evidence_hash="a" * 64
        )
        executor._agent = fake
        context = WorkflowStageContext(
            session_id="test",
            workflow_name="test-flow",
            workflow_version="1",
            goal="inspect",
            stage=_spec().stage("inspect"),
        )

        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "needs_replan")
        self.assertEqual(result.successful_actions, 0)
        self.assertEqual(result.evidence, [])
        self.assertIsNotNone(result.active)
        self.assertEqual(
            result.active.escalation.kind, ActiveEscalationKind.VERIFICATION
        )

    def test_context_mismatch_blocks_before_model_call(self) -> None:
        executor = GovernedAgentStageExecutor(self._state())
        context = WorkflowStageContext(
            session_id="wrong",
            workflow_name="test-flow",
            workflow_version="1",
            goal="inspect",
            stage=_spec().stage("inspect"),
        )
        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "blocked")
        self.assertIsNone(executor._agent)

    def test_prior_context_is_bounded_and_redacted(self) -> None:
        executor = GovernedAgentStageExecutor(self._state())

        class FakeAgent(self.FakeAgent):
            _last_task_state = TaskState(objective="inspect")

            async def run_tool_loop(
                self, prompt: str, **_kwargs: Any
            ) -> dict[str, Any]:
                self.prompt = prompt
                return {
                    "stopped": "budget",
                    "final": "step budget exhausted",
                    "steps": [],
                }

        fake = FakeAgent()
        executor._agent = fake
        context = WorkflowStageContext(
            session_id="test",
            workflow_name="test-flow",
            workflow_version="1",
            goal="inspect",
            stage=_spec().stage("inspect"),
            prior_results=[
                {
                    "stage": "previous",
                    "success": True,
                    "summary": "token=synthetic-secret",
                    "final": "X" * 5000,
                }
            ]
            * 20,
            guidance="Y" * 10000,
        )
        asyncio.run(executor(context))
        self.assertEqual(fake.prompt.count("token=[REDACTED]"), 8)
        self.assertNotIn("synthetic-secret", fake.prompt)
        self.assertNotIn("X" * 1001, fake.prompt)
        self.assertNotIn("Y" * 4001, fake.prompt)


class GovernedReadStageExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = SessionStore(db_path=self.root / "read-workflow.db")
        self.audit = AuditLayer(base_path=self.root / "audit")

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _runner(
        self,
        *,
        min_actions: int = 1,
        require_evidence: bool = True,
        max_steps: int = 8,
        expected_file_sha256: str = "",
        expected_file_path: str = "",
        expected_file_size_bytes: int | None = None,
    ) -> WorkflowRunner:
        spec = WorkflowSpec.model_validate(
            {
                "name": "read-flow",
                "description": "read one scoped file",
                "stages": [
                    {
                        "id": "inspect",
                        "title": "Inspect",
                        "objective": "read the authorized file",
                        "max_steps": max_steps,
                        "gate": {
                            "min_successful_actions": min_actions,
                            "require_evidence": require_evidence,
                            "expected_file_sha256": expected_file_sha256,
                            "expected_file_path": expected_file_path,
                            "expected_file_size_bytes": expected_file_size_bytes,
                        },
                    }
                ],
            }
        )
        return WorkflowRunner(
            registry=_Registry(spec), sessions=SessionManager(self.store)
        )

    def _executor(
        self, runner: WorkflowRunner, session_id: str, path: Path, **kwargs: Any
    ) -> GovernedReadStageExecutor:
        return GovernedReadStageExecutor(
            runner.load_state(session_id),
            ReadStageAction(
                workflow_name="read-flow",
                workflow_version="1",
                stage_id="inspect",
                capability="file_read",
                params={"path": str(path)},
                **kwargs,
            ),
            provider=LocalExecutor(),
            audit=self.audit,
        )

    def _model_executor(
        self,
        runner: WorkflowRunner,
        session_id: str,
        path: Path,
        *,
        replies: list[str] | None = None,
    ) -> GovernedAgentStageExecutor:
        class ScriptedProvider:
            def __init__(self) -> None:
                self.replies = [
                    json.dumps({"tool": "file_read", "params": {"path": str(path)}}),
                    json.dumps({"message": "inspection complete"}),
                ]
                if replies is not None:
                    self.replies = replies.copy()

            async def chat(self, _messages: list[dict[str, Any]]) -> str:
                return self.replies.pop(0)

        with (
            patch("decode.universal_agent.Config.validate", return_value=None),
            patch("decode.universal_agent.create_provider"),
            patch("decode.universal_agent.SelfLearningMemory"),
        ):
            agent = UniversalAgent(provider="openrouter")
        agent.llm = ScriptedProvider()
        agent.audit = self.audit
        agent.logging = LoggingService(base_path=self.root / "logs")
        agent.feedback = FeedbackStore(base_path=self.root / "feedback")
        agent.set_scope([])
        executor = GovernedAgentStageExecutor(
            runner.load_state(session_id), permission_mode="auto"
        )
        executor._agent = agent
        return executor

    def test_model_only_final_is_durable_verification_escalation(self) -> None:
        runner = self._runner(min_actions=0, require_evidence=False)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._model_executor(
            runner,
            created.session_id,
            self.root / "unused",
            replies=[json.dumps({"message": "claimed completion"})],
        )
        report = asyncio.run(runner.run(created.session_id, executor))
        self.assertEqual(report.status, "blocked")
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(active.outcome.value, "needs_replan")
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.VERIFICATION)
        self.assertEqual(active.attempts, 0)
        self.assertEqual(active.observations, ())
        self.assertIn("protected governed evidence", active.failed_criteria[0])

    def test_model_scope_reset_preserves_existing_execution_guard(self) -> None:
        path = self.root / "guarded.txt"
        path.write_text("controlled fixture", encoding="utf-8")
        runner = self._runner()
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._model_executor(runner, created.session_id, path)

        def existing_guard() -> str:
            return "existing execution restriction"

        executor._agent._coordinator.set_pre_execution_check(existing_guard)
        report = asyncio.run(runner.run(created.session_id, executor))
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(report.status, "blocked")
        self.assertEqual(active.observations[0].status, "blocked")
        self.assertFalse(active.observations[0].evidence_id)
        self.assertIs(executor._agent._coordinator._pre_execution_check, existing_guard)
        self.assertTrue(self.audit.query(event_type="rejection"))
        self.assertTrue(executor._agent.logging.get_logs(tool_filter="file_read"))
        self.assertTrue(executor._agent.feedback.get_execution_feedback("file_read"))

    def test_material_change_during_executable_preparation_prevents_launch(
        self,
    ) -> None:
        runner = self._runner()
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._model_executor(
            runner,
            created.session_id,
            self.root / "unused",
            replies=[
                json.dumps(
                    {
                        "tool": "shell_command",
                        "params": {"argv": [sys.executable, "--version"]},
                    }
                )
            ],
        )

        async def changed_preparation(_host: Any, _action: Any) -> None:
            await asyncio.sleep(0)
            executor._state.scope.read_roots.clear()

        with (
            patch(
                "decode.runtime.host_controller.HostController._recheck_executables",
                changed_preparation,
            ),
            patch("decode.agents.host.HostAgent.run", new_callable=AsyncMock) as launch,
        ):
            report = asyncio.run(runner.run(created.session_id, executor))
        launch.assert_not_awaited()
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(report.status, "blocked")
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.MATERIAL_CHANGE)
        self.assertEqual(active.observations[0].status, "blocked")
        self.assertTrue(self.audit.query(event_type="rejection"))

    def test_inflight_cancellation_retains_governed_request_in_both_adapters(
        self,
    ) -> None:
        for model_driven in (False, True):
            with self.subTest(model_driven=model_driven):
                path = self.root / "cancelled.txt"
                runner = self._runner()
                created = runner.start(
                    "read-flow", "inspect", read_roots=[str(self.root)]
                )
                executor = (
                    self._model_executor(runner, created.session_id, path)
                    if model_driven
                    else self._executor(runner, created.session_id, path)
                )
                with patch(
                    "decode.agents.host.HostAgent.run",
                    new_callable=AsyncMock,
                    side_effect=asyncio.CancelledError(),
                ):
                    report = asyncio.run(runner.run(created.session_id, executor))
                active = runner.load_state(created.session_id).active_nodes["inspect"]
                self.assertEqual(report.status, "blocked")
                self.assertEqual(
                    active.escalation.kind, ActiveEscalationKind.CANCELLATION
                )
                self.assertEqual(len(active.observations), 1)
                observed = active.observations[0]
                self.assertEqual(observed.status, "cancelled")
                self.assertTrue(observed.request_id)
                self.assertEqual(active.escalation.request_id, observed.request_id)
                coordinator = (
                    executor._agent._coordinator
                    if model_driven
                    else executor._coordinator
                )
                self.assertTrue(coordinator._logging.get_logs(tool_filter="file_read"))
                self.assertTrue(
                    coordinator._feedback.get_execution_feedback("file_read")
                )
                self.assertTrue(self.audit.query(event_type="tool_execution"))

    def test_model_budget_is_checkpointed_with_protected_observation(self) -> None:
        path = self.root / "budget.txt"
        path.write_text("synthetic content", encoding="utf-8")
        runner = self._runner(max_steps=1)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._model_executor(runner, created.session_id, path)
        report = asyncio.run(runner.run(created.session_id, executor))
        self.assertEqual(report.status, "blocked")
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.BUDGET)
        self.assertTrue(active.observations[0].evidence_hash)
        self.assertEqual(executor._agent._last_task_state.status.value, "blocked")
        again = asyncio.run(runner.run(created.session_id, executor))
        self.assertEqual(again.status, "blocked")
        self.assertEqual(len(executor._agent.llm.replies), 1)

    def test_model_runtime_error_or_cancellation_retains_prior_evidence(self) -> None:
        path = self.root / "interrupted.txt"
        path.write_text("synthetic content", encoding="utf-8")
        for error, kind in (
            (RuntimeError("token=synthetic-secret"), ActiveEscalationKind.EXECUTION),
            (asyncio.CancelledError(), ActiveEscalationKind.CANCELLATION),
        ):
            with self.subTest(kind=kind):
                runner = self._runner()
                created = runner.start(
                    "read-flow", "inspect", read_roots=[str(self.root)]
                )
                executor = self._model_executor(runner, created.session_id, path)
                executor._agent.llm.chat = AsyncMock(
                    side_effect=[
                        json.dumps(
                            {"tool": "file_read", "params": {"path": str(path)}}
                        ),
                        error,
                    ]
                )
                report = asyncio.run(runner.run(created.session_id, executor))
                active = runner.load_state(created.session_id).active_nodes["inspect"]
                self.assertEqual(active.escalation.kind, kind)
                self.assertEqual(len(active.observations), 1)
                self.assertTrue(active.observations[0].evidence_hash)
                self.assertNotIn("synthetic-secret", report.message)
                self.assertNotEqual(report.status, "complete")

    def test_denied_write_stops_without_replay_or_side_effect(self) -> None:
        path = self.root / "must-not-exist.txt"
        runner = self._runner(min_actions=0, require_evidence=False)
        created = runner.start(
            "read-flow",
            "inspect",
            read_roots=[str(self.root)],
            write_roots=[str(self.root)],
        )
        call = json.dumps(
            {
                "tool": "file_write",
                "params": {"path": str(path), "content": "synthetic"},
            }
        )
        executor = self._model_executor(
            runner,
            created.session_id,
            path,
            replies=[call, call, json.dumps({"message": "done"})],
        )
        executor._permission_mode = PermissionMode.ASK
        executor._approval_callback = AsyncMock(return_value=False)
        report = asyncio.run(runner.run(created.session_id, executor))
        self.assertEqual(report.status, "blocked")
        self.assertFalse(path.exists())
        self.assertEqual(len(executor._agent.llm.replies), 2)
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(len(active.observations), 1)
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.APPROVAL)

    def test_material_stage_change_is_governed_before_call(self) -> None:
        path = self.root / "material.txt"
        path.write_text("synthetic content", encoding="utf-8")
        runner = self._runner()
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._model_executor(runner, created.session_id, path)

        async def change_scope(_messages: list[dict[str, Any]]) -> str:
            executor._state.scope.write_roots.append(str(self.root))
            return json.dumps({"tool": "file_read", "params": {"path": str(path)}})

        executor._agent.llm.chat = AsyncMock(side_effect=change_scope)
        report = asyncio.run(runner.run(created.session_id, executor))
        self.assertEqual(report.status, "blocked")
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.MATERIAL_CHANGE)
        self.assertEqual(active.observations[0].status, "blocked")
        self.assertEqual(active.observations[0].evidence_hash, "")
        self.assertTrue(self.audit.query(event_type="rejection"))
        self.assertTrue(executor._agent.logging.get_logs(tool_filter="file_read"))
        self.assertTrue(executor._agent.feedback.get_execution_feedback("file_read"))

    def test_material_change_during_approval_blocks_authorized_write(self) -> None:
        path = self.root / "approval-race.txt"
        runner = self._runner(min_actions=0, require_evidence=False)
        created = runner.start(
            "read-flow",
            "inspect",
            read_roots=[str(self.root)],
            write_roots=[str(self.root)],
        )
        executor = self._model_executor(
            runner,
            created.session_id,
            path,
            replies=[
                json.dumps(
                    {
                        "tool": "file_write",
                        "params": {"path": str(path), "content": "synthetic"},
                    }
                )
            ],
        )
        executor._permission_mode = PermissionMode.ASK

        async def approve_after_change(_request: Any) -> bool:
            executor._state.scope.write_roots.clear()
            return True

        executor._approval_callback = approve_after_change
        report = asyncio.run(runner.run(created.session_id, executor))
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(report.status, "blocked")
        self.assertFalse(path.exists())
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.MATERIAL_CHANGE)
        self.assertEqual(active.observations[0].status, "blocked")
        self.assertIsNone(executor._agent._coordinator._pre_execution_check)
        self.assertTrue(executor._agent.logging.get_logs(tool_filter="file_write"))
        self.assertTrue(executor._agent.feedback.get_execution_feedback("file_write"))
        self.assertTrue(self.audit.query(event_type="rejection"))

    def test_read_runtime_exception_or_cancellation_is_typed_and_not_retried(
        self,
    ) -> None:
        for error, kind in (
            (OSError("password=synthetic-secret"), ActiveEscalationKind.EXECUTION),
            (asyncio.CancelledError(), ActiveEscalationKind.CANCELLATION),
        ):
            with self.subTest(kind=kind):
                runner = self._runner()
                created = runner.start(
                    "read-flow", "inspect", read_roots=[str(self.root)]
                )
                executor = self._executor(
                    runner, created.session_id, self.root / "unused", max_attempts=2
                )
                executor._host.run = AsyncMock(side_effect=error)
                report = asyncio.run(runner.run(created.session_id, executor))
                active = runner.load_state(created.session_id).active_nodes["inspect"]
                self.assertEqual(active.escalation.kind, kind)
                self.assertEqual(executor._host.run.await_count, 1)
                self.assertNotIn("synthetic-secret", report.message)
                self.assertNotEqual(report.status, "complete")

    def _provider_stage_conformance(self, provider: Any, query: str) -> None:
        for model_driven in (False, True):
            with self.subTest(model_driven=model_driven):
                runner = self._runner()
                created = runner.start(
                    "read-flow", "inspect", read_roots=[str(self.root)]
                )
                if model_driven:
                    executor = self._model_executor(
                        runner,
                        created.session_id,
                        self.root / "unused",
                        replies=[
                            json.dumps(
                                {"tool": "list_tools", "params": {"query": query}}
                            ),
                            json.dumps({"message": "discovery complete"}),
                        ],
                    )
                    executor._agent.execution_provider = provider
                else:
                    executor = GovernedReadStageExecutor(
                        runner.load_state(created.session_id),
                        ReadStageAction(
                            workflow_name="read-flow",
                            workflow_version="1",
                            stage_id="inspect",
                            capability="list_tools",
                            params={"query": query},
                        ),
                        provider=provider,
                        audit=self.audit,
                    )
                report = asyncio.run(runner.run(created.session_id, executor))
                self.assertEqual(report.status, "complete", report.message)
                state = runner.load_state(created.session_id)
                active = state.active_nodes["inspect"]
                self.assertEqual(active.observations[0].provider, provider.name)
                self.assertTrue(active.gate_passed)
                self.assertTrue(active.observations[0].evidence_hash)
                coordinator = (
                    executor._agent._coordinator
                    if model_driven
                    else executor._coordinator
                )
                evidence = active.observations[0]
                stored = (
                    coordinator._evidence.base_path / f"{evidence.evidence_id}.evidence"
                )
                self.assertEqual(
                    hashlib.sha256(stored.read_bytes()).hexdigest(),
                    evidence.evidence_hash,
                )
                self.assertTrue(coordinator._logging.get_logs(tool_filter="list_tools"))
                self.assertTrue(
                    coordinator._feedback.get_execution_feedback("list_tools")
                )
                self.assertTrue(self.audit.query(event_type="tool_execution"))
                replayed = asyncio.run(runner.run(created.session_id, executor))
                self.assertEqual(replayed.status, "complete")
                self.assertEqual(
                    len(
                        runner.load_state(created.session_id)
                        .active_nodes["inspect"]
                        .observations
                    ),
                    1,
                )

    def test_local_active_stage_conformance_with_and_without_model(self) -> None:
        self._provider_stage_conformance(
            LocalExecutor(), "cmd" if sys.platform == "win32" else "printf"
        )

    def test_model_stage_handoff_refreshes_dependency_evidence_and_fences_replay(
        self,
    ) -> None:
        path = self.root / "handoff.txt"
        path.write_text("synthetic content", encoding="utf-8")
        spec = WorkflowSpec.model_validate(
            {
                "name": "read-flow",
                "description": "two bounded nodes",
                "stages": [
                    {
                        "id": "inspect",
                        "title": "Inspect",
                        "objective": "inspect",
                        "gate": {"min_successful_actions": 1, "require_evidence": True},
                    },
                    {
                        "id": "verify",
                        "title": "Verify",
                        "objective": "verify",
                        "depends_on": ["inspect"],
                        "gate": {"min_successful_actions": 1, "require_evidence": True},
                    },
                ],
            }
        )
        runner = WorkflowRunner(
            registry=_Registry(spec), sessions=SessionManager(self.store)
        )
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._model_executor(
            runner,
            created.session_id,
            path,
            replies=[
                json.dumps({"tool": "file_read", "params": {"path": str(path)}}),
                json.dumps({"message": "first node complete"}),
                json.dumps({"tool": "file_read", "params": {"path": str(path)}}),
                json.dumps({"message": "second node complete"}),
            ],
        )
        seen: list[str] = []
        original_chat = executor._agent.llm.chat

        async def record_context(messages: list[dict[str, Any]]) -> str:
            seen.append(messages[1]["content"])
            return await original_chat(messages)

        executor._agent.llm.chat = record_context
        report = asyncio.run(runner.run(created.session_id, executor))
        self.assertEqual(report.completed, ["inspect", "verify"])
        state = runner.load_state(created.session_id)
        first_evidence = state.active_nodes["inspect"].observations[0].evidence_id
        self.assertIn(first_evidence, seen[2])
        self.assertNotIn("synthetic content", seen[2])
        asyncio.run(runner.run(created.session_id, executor))
        self.assertEqual(len(seen), 4)

    @unittest.skipUnless(
        sys.platform == "win32" and os.environ.get("DECODE_RUN_WSL_CONFORMANCE") == "1",
        "requires explicit Kali WSL conformance opt-in",
    )
    def test_kali_active_stage_conformance_with_and_without_model(self) -> None:
        from decode.execution import WSLExecutor

        self._provider_stage_conformance(WSLExecutor(distro="kali-linux"), "printf")

    @unittest.skipUnless(
        os.environ.get("DECODE_GOVERNED_DOCKER_IMAGE", ""),
        "requires a cached GNU-compatible Docker image",
    )
    def test_docker_active_stage_conformance_with_and_without_model(self) -> None:
        from decode.execution import DockerExecutor

        self._provider_stage_conformance(
            DockerExecutor(
                image=os.environ["DECODE_GOVERNED_DOCKER_IMAGE"], network="none"
            ),
            "printf",
        )

    def test_model_free_read_completes_with_governed_evidence_and_telemetry(
        self,
    ) -> None:
        path = self.root / "sample.txt"
        path.write_text("synthetic test content", encoding="utf-8")
        runner = self._runner()
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._executor(runner, created.session_id, path)

        report = asyncio.run(runner.run(created.session_id, executor))

        self.assertEqual(report.status, "complete")
        self.assertEqual(report.completed, ["inspect"])
        state = runner.load_state(created.session_id)
        self.assertEqual(len(state.artifacts), 1)
        self.assertTrue(state.artifacts[0].evidence_hash)
        self.assertTrue(self.audit.query(event_type="tool_execution"))
        self.assertTrue(
            executor._coordinator._logging.get_logs(tool_filter="file_read")
        )
        self.assertTrue(
            executor._coordinator._feedback.get_execution_feedback("file_read")
        )

    def test_expected_file_digest_completes_with_bound_durable_provenance(
        self,
    ) -> None:
        content = "synthetic digest content"
        path = self.root / "digest.txt"
        path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode()).hexdigest()
        runner = self._runner(expected_file_sha256=digest, expected_file_path=str(path))
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])

        report = asyncio.run(
            runner.run(
                created.session_id,
                self._executor(runner, created.session_id, path),
            )
        )

        self.assertEqual(report.status, "complete")
        state = runner.load_state(created.session_id)
        active = state.active_nodes["inspect"]
        self.assertEqual(
            active.workflow_fingerprint, runner.registry.spec.fingerprint()
        )
        self.assertEqual(
            active.node_fingerprint,
            state.plan.nodes["inspect"].material_fingerprint(),
        )
        self.assertTrue(active.gate_passed)
        self.assertEqual(
            active.observations[0].signals,
            {
                "file_sha256": digest,
                "file_size_bytes": str(len(content.encode())),
                "file_path_sha256": file_path_fingerprint(str(path)),
            },
        )
        self.assertEqual(
            active.observations[0].evidence_hash, state.artifacts[0].evidence_hash
        )
        self.assertNotIn(content, str(active))
        self.assertNotIn(str(path), str(active))

    def test_same_bytes_at_other_path_cannot_satisfy_artifact_gate(self) -> None:
        content = "synthetic artifact"
        expected = self.root / "expected.txt"
        actual = self.root / "other.txt"
        expected.write_text(content, encoding="utf-8")
        actual.write_text(content, encoding="utf-8")
        runner = self._runner(
            expected_file_sha256=hashlib.sha256(content.encode()).hexdigest(),
            expected_file_path=str(expected),
        )
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])

        report = asyncio.run(
            runner.run(
                created.session_id,
                self._executor(runner, created.session_id, actual),
            )
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.needs_review, ["inspect"])
        self.assertIn("governed file path", report.message)
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertFalse(active.gate_passed)
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.VERIFICATION)

    def test_digest_mismatch_pauses_even_with_valid_action_and_evidence(self) -> None:
        path = self.root / "digest.txt"
        path.write_text("synthetic digest content", encoding="utf-8")
        runner = self._runner(expected_file_sha256="0" * 64)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])

        report = asyncio.run(
            runner.run(
                created.session_id,
                self._executor(runner, created.session_id, path),
            )
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.needs_review, ["inspect"])
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(active.outcome.value, "needs_replan")
        self.assertFalse(active.gate_passed)
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.VERIFICATION)
        self.assertIn("governed file digest", report.message)

    def test_model_stage_carries_governed_file_metadata_into_typed_result(
        self,
    ) -> None:
        content = "synthetic model read"
        path = self.root / "model.txt"
        path.write_text(content, encoding="utf-8")
        runner = self._runner(
            expected_file_sha256=hashlib.sha256(content.encode()).hexdigest(),
            expected_file_path=str(path),
            expected_file_size_bytes=len(content.encode()),
        )
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])

        report = asyncio.run(
            runner.run(
                created.session_id,
                self._model_executor(runner, created.session_id, path),
            )
        )

        self.assertEqual(report.status, "complete")
        state = runner.load_state(created.session_id)
        active = state.active_nodes["inspect"]
        self.assertEqual(active.observations[0].capability, "file_read")
        self.assertEqual(active.observations[0].provider, "internal")
        self.assertEqual(
            active.observations[0].signals["file_size_bytes"],
            str(len(content.encode())),
        )
        self.assertEqual(
            active.observations[0].signals["file_path_sha256"],
            file_path_fingerprint(str(path)),
        )
        self.assertEqual(
            active.observations[0].evidence_hash, state.artifacts[0].evidence_hash
        )
        self.assertNotIn(content, str(active))

    def test_model_stage_file_size_mismatch_pauses_despite_final_answer(self) -> None:
        path = self.root / "model.txt"
        path.write_text("synthetic model read", encoding="utf-8")
        runner = self._runner(expected_file_size_bytes=1000)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])

        report = asyncio.run(
            runner.run(
                created.session_id,
                self._model_executor(runner, created.session_id, path),
            )
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.needs_review, ["inspect"])
        self.assertIn("governed file size", report.message)
        self.assertEqual(
            runner.load_state(created.session_id).active_nodes["inspect"].outcome.value,
            "needs_replan",
        )

    def test_model_final_cannot_complete_after_only_a_denied_governed_read(
        self,
    ) -> None:
        path = self.root / "outside.txt"
        path.write_text("synthetic content", encoding="utf-8")
        allowed = self.root / "allowed"
        allowed.mkdir()
        runner = self._runner(min_actions=0, require_evidence=False)
        created = runner.start("read-flow", "inspect", read_roots=[str(allowed)])

        report = asyncio.run(
            runner.run(
                created.session_id,
                self._model_executor(runner, created.session_id, path),
            )
        )

        self.assertEqual(report.status, "blocked")
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(active.outcome.value, "blocked")
        self.assertFalse(active.observations[0].success)
        self.assertEqual(active.observations[0].capability, "file_read")
        self.assertEqual(
            active.escalation.request_id, active.observations[0].request_id
        )
        self.assertTrue(self.audit.query(event_type="tool_execution"))

    def test_active_result_with_wrong_node_fingerprint_is_blocked(self) -> None:
        path = self.root / "digest.txt"
        path.write_text("synthetic digest content", encoding="utf-8")
        runner = self._runner()
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._executor(runner, created.session_id, path)

        async def tampered(context: WorkflowStageContext) -> StageResult:
            result = await executor(context)
            assert result.active is not None
            return result.model_copy(
                update={
                    "active": result.active.model_copy(
                        update={"node_fingerprint": "0" * 64}
                    )
                }
            )

        report = asyncio.run(runner.run(created.session_id, tampered))
        self.assertEqual(report.status, "blocked")
        self.assertIn("does not match the durable workflow node", report.message)
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.MATERIAL_CHANGE)
        self.assertEqual(active.observations, ())

    def test_digest_criterion_rejects_untyped_evidence_or_malformed_digest(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            self._runner(expected_file_sha256="not-a-digest")
        gate = (
            self._runner(expected_file_sha256="0" * 64)
            .registry.spec.stage("inspect")
            .gate
        )
        valid, failures = gate.check(
            StageResult(
                success=True,
                final="done",
                successful_actions=1,
                evidence=[EvidenceLink(id="artifact", sha256="0" * 64)],
            )
        )
        self.assertFalse(valid)
        self.assertIn(
            "governed file digest does not match the expected SHA-256", failures
        )

    def test_out_of_scope_read_fails_without_recovery(self) -> None:
        path = self.root / "sample.txt"
        path.write_text("synthetic test content", encoding="utf-8")
        allowed = self.root / "allowed"
        allowed.mkdir()
        runner = self._runner()
        created = runner.start("read-flow", "inspect", read_roots=[str(allowed)])
        executor = self._executor(runner, created.session_id, path, max_attempts=2)
        executor._host.run = AsyncMock(wraps=executor._host.run)

        report = asyncio.run(runner.run(created.session_id, executor))

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.failed, ["inspect"])
        self.assertFalse(runner.load_state(created.session_id).observations[-1].success)
        self.assertEqual(executor._host.run.await_count, 1)

    def test_success_without_required_action_count_pauses_for_replan(self) -> None:
        path = self.root / "sample.txt"
        path.write_text("synthetic test content", encoding="utf-8")
        runner = self._runner(min_actions=2)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._executor(runner, created.session_id, path)

        report = asyncio.run(runner.run(created.session_id, executor))

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.needs_review, ["inspect"])

    def test_timeout_retry_is_bounded_and_denial_is_not_retried(self) -> None:
        runner = self._runner(require_evidence=False)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._executor(
            runner, created.session_id, self.root / "sample.txt", max_attempts=2
        )
        context = runner._context(
            runner.load_state(created.session_id),
            runner.registry.spec,
            runner.registry.spec.stage("inspect"),
        )
        timeout = CoordinatedResult(
            request_id="one",
            action="file_read",
            status=ExecutionStatus.TIMEOUT,
            error_category=ExecutionErrorCategory.TIMEOUT,
        )
        success = CoordinatedResult(
            request_id="two",
            action="file_read",
            status=ExecutionStatus.SUCCESS,
            success=True,
            evidence=EvidenceReference(
                id="read-evidence",
                sha256="a" * 64,
                size_bytes=1,
                path=str(self.root / "read-evidence.evidence"),
                mime_type="text/plain",
                created_at="2026-10-01T00:00:00+00:00",
            ),
        )
        executor._host.run = AsyncMock(side_effect=[timeout, success])

        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "completed")
        self.assertEqual(result.data["attempts"], 2)
        self.assertIsNone(result.active.escalation)
        self.assertEqual(result.active.observations[0].error_category, "timeout")
        self.assertEqual(
            [item.request_id for item in result.active.observations], ["one", "two"]
        )
        self.assertEqual(executor._host.run.await_count, 2)

        repeated = asyncio.run(executor(context))
        self.assertEqual(repeated.outcome.value, "blocked")
        self.assertEqual(executor._host.run.await_count, 2)

        denied = CoordinatedResult(
            request_id="three",
            action="file_read",
            status=ExecutionStatus.DENIED,
            error_category=ExecutionErrorCategory.POLICY_DENIAL,
        )
        executor = self._executor(
            runner, created.session_id, self.root / "sample.txt", max_attempts=2
        )
        executor._host.run = AsyncMock(return_value=denied)
        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "blocked")
        self.assertEqual(result.active.escalation.kind, ActiveEscalationKind.POLICY)
        self.assertEqual(result.active.escalation.request_id, "three")
        self.assertEqual(executor._host.run.await_count, 1)

    def test_retry_needs_timeout_category_and_unchanged_action(self) -> None:
        runner = self._runner(require_evidence=False)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        context = runner._context(
            runner.load_state(created.session_id),
            runner.registry.spec,
            runner.registry.spec.stage("inspect"),
        )
        executor = self._executor(
            runner, created.session_id, self.root / "sample.txt", max_attempts=2
        )
        ambiguous = CoordinatedResult(
            request_id="one",
            action="file_read",
            status=ExecutionStatus.TIMEOUT,
            error_category=ExecutionErrorCategory.EXECUTION_FAILURE,
        )
        executor._host.run = AsyncMock(return_value=ambiguous)
        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "failed")
        self.assertEqual(executor._host.run.await_count, 1)

        executor = self._executor(
            runner, created.session_id, self.root / "sample.txt", max_attempts=2
        )
        timed_out = CoordinatedResult(
            request_id="two",
            action="file_read",
            status=ExecutionStatus.TIMEOUT,
            error_category=ExecutionErrorCategory.TIMEOUT,
        )

        async def mutate_action(
            _capability: str, _params: dict[str, Any]
        ) -> CoordinatedResult:
            executor._action.params["path"] = str(self.root / "different.txt")
            return timed_out

        executor._host.run = AsyncMock(side_effect=mutate_action)
        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "blocked")
        self.assertEqual(
            result.active.escalation.kind, ActiveEscalationKind.MATERIAL_CHANGE
        )
        self.assertEqual(result.active.attempts, 1)
        self.assertEqual(len(result.active.observations), 2)
        self.assertEqual(executor._host.run.await_count, 1)

    def test_action_is_bound_to_stage_and_rejects_commands(self) -> None:
        with self.assertRaises(ValidationError):
            ReadStageAction(
                workflow_name="read-flow",
                workflow_version="1",
                stage_id="inspect",
                capability="shell_command",
                params={"argv": ["cat", "sample.txt"]},
            )
        runner = self._runner()
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._executor(runner, created.session_id, self.root / "sample.txt")
        context = runner._context(
            runner.load_state(created.session_id),
            runner.registry.spec,
            runner.registry.spec.stage("inspect"),
        )
        context.session_id = "wrong-session"
        executor._host.run = AsyncMock()

        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "blocked")
        executor._host.run.assert_not_awaited()
        self.assertTrue(self.audit.query(event_type="rejection"))
        self.assertTrue(
            executor._coordinator._logging.get_logs(tool_filter="file_read")
        )
        self.assertTrue(
            executor._coordinator._feedback.get_execution_feedback("file_read")
        )

    def test_read_retry_cannot_exceed_stage_step_budget(self) -> None:
        runner = self._runner(max_steps=1)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._executor(
            runner, created.session_id, self.root / "sample.txt", max_attempts=2
        )
        context = runner._context(
            runner.load_state(created.session_id),
            runner.registry.spec,
            runner.registry.spec.stage("inspect"),
        )
        executor._host.run = AsyncMock()

        result = asyncio.run(executor(context))
        self.assertEqual(result.outcome.value, "blocked")
        self.assertEqual(result.active.escalation.kind, ActiveEscalationKind.BUDGET)
        self.assertEqual(result.active.attempts, 0)
        self.assertEqual(result.active.observations[0].status, "blocked")
        executor._host.run.assert_not_awaited()

    def test_approval_required_read_escalates_without_retry(self) -> None:
        runner = self._runner(require_evidence=False)
        created = runner.start("read-flow", "inspect", read_roots=[str(self.root)])
        executor = self._executor(
            runner, created.session_id, self.root / "sample.txt", max_attempts=2
        )
        context = runner._context(
            runner.load_state(created.session_id),
            runner.registry.spec,
            runner.registry.spec.stage("inspect"),
        )
        executor._host.run = AsyncMock(
            return_value=CoordinatedResult(
                request_id="approval-one",
                action="file_read",
                status=ExecutionStatus.DENIED,
                error_category=ExecutionErrorCategory.APPROVAL_REQUIRED,
            )
        )

        result = asyncio.run(executor(context))

        self.assertEqual(result.outcome.value, "blocked")
        self.assertEqual(result.active.escalation.kind, ActiveEscalationKind.APPROVAL)
        self.assertEqual(result.active.escalation.request_id, "approval-one")
        executor._host.run.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
