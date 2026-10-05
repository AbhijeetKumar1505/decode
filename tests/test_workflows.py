import asyncio
import hashlib
import importlib
import json
import os
import sqlite3
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
    CoreBudgetState,
    CoreIntent,
    CoreMissionBudget,
    CoreMissionStop,
    CoreReplanTransition,
    CoreReviewRequest,
    CoreReviewResolution,
    CoreStageDecision,
    CoreStrategy,
    CoreWorkflowPlanner,
    CoreWorkflowSelection,
    EvidenceLink,
    GovernedReadStageExecutor,
    ReadStageAction,
    ReviewedWorkflow,
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

    def all(self) -> list[WorkflowSpec]:
        return [self.spec]


class CoreWorkflowPlannerTest(unittest.TestCase):
    def test_mission_budget_contracts_are_strict_and_reservations_conservative(
        self,
    ) -> None:
        limits = CoreMissionBudget(max_stage_dispatches=2, max_reserved_steps=16)
        budget = CoreBudgetState(limits=limits)
        first = budget.reserve(8)
        second = first.reserve(8)
        self.assertEqual(budget.stage_dispatches, 0)
        self.assertEqual(second.reserved_steps, 16)
        self.assertEqual(
            second.stop_reason(1), "mission stage-dispatch budget exhausted"
        )
        with self.assertRaises(ValueError):
            second.reserve(1)
        for steps in (0, 33, True, 1.5):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                budget.reserve(steps)
        for updates in (
            {"max_stage_dispatches": -1},
            {"max_stage_dispatches": True},
            {"max_stage_dispatches": 1025},
            {"max_reserved_steps": 32769},
            {"max_reserved_steps": "8"},
            {"approved": True},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                CoreMissionBudget.model_validate({**limits.model_dump(), **updates})
        for dispatches, steps in ((0, 1), (1, 0), (1, 33), (3, 8), (1, 17), (2, 1)):
            with (
                self.subTest(dispatches=dispatches, steps=steps),
                self.assertRaises(ValidationError),
            ):
                CoreBudgetState(
                    limits=limits, stage_dispatches=dispatches, reserved_steps=steps
                )

    @staticmethod
    def _review(spec: WorkflowSpec) -> ReviewedWorkflow:
        return ReviewedWorkflow(
            name=spec.name, version=spec.version, fingerprint=spec.fingerprint()
        )

    def test_selects_only_reviewed_mode_with_bound_criteria(self) -> None:
        registry = WorkflowRegistry()
        reviewed = tuple(self._review(spec) for spec in registry.all())
        decision = CoreWorkflowPlanner(registry).select(
            CoreIntent(objective="inspect repository", mode="coding"), reviewed
        )
        self.assertEqual(decision.outcome, "selected")
        self.assertEqual(decision.workflow.name, "engineering-delivery")
        spec = registry.get(decision.workflow.name)
        self.assertEqual(
            decision.criteria, {stage.id: stage.gate for stage in spec.stages}
        )
        self.assertEqual(decision.workflow.fingerprint, spec.fingerprint())
        self.assertEqual(
            decision.public_reason, "only compatible reviewed workflow selected"
        )

    def test_security_ambiguity_requires_explicit_choice(self) -> None:
        registry = WorkflowRegistry()
        reviewed = tuple(self._review(spec) for spec in registry.all())
        planner = CoreWorkflowPlanner(registry)
        decision = planner.select(
            CoreIntent(objective="review", mode="security"), reviewed
        )
        self.assertEqual(decision.outcome, "needs_input")
        self.assertIsNone(decision.workflow)
        self.assertEqual(decision.criteria, {})
        explicit = planner.select(
            CoreIntent(
                objective="review", mode="security", workflow_name="security-code-audit"
            ),
            reviewed,
        )
        self.assertEqual(explicit.outcome, "selected")
        self.assertEqual(explicit.public_reason, "explicit reviewed workflow selected")

    def test_empty_review_set_and_unreviewed_request_never_select(self) -> None:
        planner = CoreWorkflowPlanner(_Registry(_spec()))
        self.assertEqual(
            planner.select(CoreIntent(objective="inspect", mode="hybrid"), ()).outcome,
            "needs_input",
        )
        decision = planner.select(
            CoreIntent(objective="inspect", mode="hybrid", workflow_name="test-flow"),
            (),
        )
        self.assertEqual(decision.outcome, "blocked")
        self.assertEqual(decision.public_reason, "requested workflow is not reviewed")

    def test_changed_missing_or_wrong_mode_workflow_is_blocked(self) -> None:
        spec = _spec()
        pin = self._review(spec)
        planner = CoreWorkflowPlanner(_Registry(spec))
        decision = planner.select(
            CoreIntent(objective="inspect", mode="coding", workflow_name=spec.name),
            (pin,),
        )
        self.assertEqual(
            decision.public_reason, "requested workflow mode does not match intent"
        )
        intent = CoreIntent(objective="inspect", mode="hybrid", workflow_name=spec.name)
        for field, value in (
            ("version", "2"),
            ("guidance", "modified"),
            ("name", "removed"),
        ):
            with self.subTest(field=field):
                changed = spec.model_copy(deep=True)
                setattr(changed, field, value)
                decision = CoreWorkflowPlanner(_Registry(changed)).select(
                    intent, (pin,)
                )
                self.assertEqual(decision.outcome, "blocked")
                self.assertEqual(
                    decision.public_reason, "reviewed workflow is missing or changed"
                )

    def test_requests_cannot_supply_scope_commands_or_approval(self) -> None:
        for payload in (
            {"objective": " ", "mode": "coding"},
            {"objective": "inspect", "mode": "coding", "approved": True},
            {"objective": "inspect", "mode": "coding", "scope": ["*"]},
            {"objective": "inspect", "mode": "coding", "command": "whoami"},
            {"objective": "inspect", "mode": "coding", "workflow_name": "../workflow"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                CoreIntent.model_validate(payload)
        pin = self._review(_spec())
        with self.assertRaises(ValidationError):
            ReviewedWorkflow.model_validate(
                {**pin.model_dump(), "allow_destructive": True}
            )
        with self.assertRaises(ValueError):
            CoreWorkflowPlanner(_Registry(_spec())).select(
                CoreIntent(objective="inspect", mode="hybrid"), (pin, pin)
            )
        with self.assertRaises(ValueError):
            CoreWorkflowPlanner(_Registry(_spec())).select(
                CoreIntent(objective="inspect", mode="hybrid"), (pin,) * 65
            )

    def test_public_reason_does_not_echo_objective_or_workflow_text(self) -> None:
        spec = _spec()
        spec.guidance = "token=private-workflow-secret"
        decision = CoreWorkflowPlanner(_Registry(spec)).select(
            CoreIntent(objective="token=private-objective-secret", mode="hybrid"),
            (self._review(spec),),
        )
        self.assertNotIn("private-", decision.model_dump_json())
        with self.assertRaises(ValidationError):
            CoreWorkflowSelection.model_validate(
                {**decision.model_dump(), "outcome": "blocked"}
            )


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

    def _core_run(
        self, *, independent: bool = False, budget: CoreMissionBudget | None = None
    ) -> str:
        spec = self.runner.registry.spec
        if independent:
            spec.stages = [spec.stage("inspect"), spec.stage("finish")]
            spec.stage("finish").depends_on = []
        return self.runner.start_core(
            CoreIntent(objective="inspect controlled fixtures", mode="hybrid"),
            (CoreWorkflowPlannerTest._review(spec),),
            budget=budget,
        ).session_id

    def _budget(self, session: str) -> CoreBudgetState:
        return CoreBudgetState.model_validate(
            self.runner.load_state(session).environment["core_budget"]
        )

    def _replacement(self) -> WorkflowSpec:
        original = self.runner.registry.spec
        replacement = original.model_copy(deep=True)
        replacement.name = "replacement-flow"
        replacement.stages = [replacement.stage("inspect")]
        mapping = {original.name: original, replacement.name: replacement}
        self.runner.registry.get = mapping.get
        return replacement

    def _replace(self, decision: CoreStageDecision, spec: WorkflowSpec) -> Any:
        state = self.runner.load_state(decision.session_id)
        return self.runner.replan_core(
            decision,
            CoreIntent(
                objective=state.objective, mode=state.mode, workflow_name=spec.name
            ),
            (CoreWorkflowPlannerTest._review(spec),),
        )

    def test_core_strategy_is_persisted_bound_and_not_model_selected(self) -> None:
        session = self._core_run()
        state = self.runner.load_state(session)
        strategy = CoreStrategy.model_validate(state.environment["core_strategy"])
        self.assertEqual(strategy, CoreStrategy.from_spec(self.runner.registry.spec))
        self.assertEqual(strategy.stage_order, ("inspect", "approve", "finish"))
        state.environment["core_strategy"]["stage_order"] = [
            "finish",
            "inspect",
            "approve",
        ]
        self.runner._states.save(state)
        with self.assertRaisesRegex(ValueError, "strategy no longer matches"):
            self.runner.decide_core(session)

    def test_core_issued_identifier_rejects_stale_wrong_and_consumed(self) -> None:
        session = self._core_run()
        decision = self.runner.decide_core(session)
        self.assertEqual(
            self.runner.issued_core(session, decision.fingerprint()), decision
        )
        with self.assertRaises(ValueError):
            self.runner.issued_core(session, "a" * 64)
        self.runner.stop_core(decision)
        with self.assertRaises(ValueError):
            self.runner.issued_core(session, decision.fingerprint())

    def test_core_operator_stop_never_executes_or_resumes(self) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=2, max_reserved_steps=16)
        )
        decision = self.runner.decide_core(session)
        before = self.runner.load_state(session)
        self.runner.stop_core(decision)
        stopped = self.runner.load_state(session)
        self.assertEqual(stopped.plan, before.plan)
        self.assertEqual(stopped.scope, before.scope)
        self.assertEqual(self._budget(session).stage_dispatches, 0)
        self.assertEqual(
            CoreMissionStop.model_validate(stopped.environment["core_stop"]).decision,
            decision,
        )
        executor = AsyncMock()
        fresh = self.runner.decide_core(session)
        self.assertEqual(fresh.outcome, "stopped")
        asyncio.run(self.runner.run_core(fresh, executor))
        with self.assertRaises(ValueError):
            asyncio.run(self.runner.run(session, executor))
        with self.assertRaises(ValueError):
            self.runner.approve_core_stage(self.runner.decide_core(session))
        executor.assert_not_called()

    def test_core_stop_failure_and_staleness_fail_closed(self) -> None:
        session = self._core_run()
        decision = self.runner.decide_core(session)
        before = self.runner.load_state(session)
        with (
            patch.object(
                self.runner._states, "save", side_effect=OSError("controlled failure")
            ),
            self.assertRaises(OSError),
        ):
            self.runner.stop_core(decision)
        self.assertEqual(self.runner.load_state(session), before)
        state = self.runner.load_state(session)
        state.scope.targets.append("192.0.2.1")
        self.runner._states.save(state)
        with self.assertRaises(ValueError):
            self.runner.stop_core(decision)

    def test_core_human_replan_preserves_authority_budget_and_old_evidence(
        self,
    ) -> None:
        session, decision = self._core_review_stop(
            ActiveEscalationKind.VERIFICATION, "needs_replan"
        )
        before = self.runner.load_state(session)
        replacement = self._replacement()
        created = self._replace(decision, replacement)
        parent = self.runner.load_state(session)
        child = self.runner.load_state(created.session_id)
        self.assertEqual(parent.plan, before.plan)
        self.assertEqual(parent.active_nodes, before.active_nodes)
        self.assertEqual(parent.observations, before.observations)
        self.assertEqual(child.scope, before.scope)
        self.assertEqual(child.objective, before.objective)
        self.assertEqual(child.mode, before.mode)
        self.assertEqual(
            child.environment["core_budget"], before.environment["core_budget"]
        )
        self.assertEqual(child.actions, [])
        self.assertEqual(child.observations, [])
        self.assertEqual(child.active_nodes, {})
        self.assertTrue(
            all(node.status == "pending" for node in child.plan.nodes.values())
        )
        self.assertEqual(self.runner.decide_core(session).outcome, "stopped")
        transition = CoreReplanTransition.model_validate(
            parent.environment["core_replan_transition"]
        )
        self.assertEqual(transition.replacement_session_id, child.session_id)
        asyncio.run(
            self.runner.run_core(
                self.runner.decide_core(child.session_id), self._typed_executor
            )
        )
        self.assertEqual(self._budget(child.session_id).stage_dispatches, 2)
        self.assertEqual(self.runner.decide_core(child.session_id).outcome, "complete")
        with self.assertRaises(ValueError):
            self._replace(decision, replacement)

    def test_core_replan_rejects_changed_goal_mode_unreviewed_and_stale(self) -> None:
        session, decision = self._core_review_stop(ActiveEscalationKind.POLICY)
        replacement = self._replacement()
        before = self.runner.load_state(session)
        for objective, mode, reviewed in (
            (
                "changed objective",
                "hybrid",
                (CoreWorkflowPlannerTest._review(replacement),),
            ),
            (
                before.objective,
                "coding",
                (CoreWorkflowPlannerTest._review(replacement),),
            ),
            (before.objective, "hybrid", ()),
            (
                before.objective,
                "hybrid",
                (
                    CoreWorkflowPlannerTest._review(replacement).model_copy(
                        update={"fingerprint": "a" * 64}
                    ),
                ),
            ),
        ):
            with (
                self.subTest(mode=mode, reviewed=bool(reviewed)),
                self.assertRaises(ValueError),
            ):
                self.runner.replan_core(
                    decision,
                    CoreIntent(
                        objective=objective, mode=mode, workflow_name=replacement.name
                    ),
                    reviewed,
                )
            self.assertEqual(self.runner.load_state(session), before)
        self.runner.review_core(
            CoreReviewResolution(decision=decision, disposition="acknowledged")
        )
        with self.assertRaises(ValueError):
            self._replace(decision, replacement)

    def test_core_replan_cannot_apply_during_ready_running_or_interrupted_work(
        self,
    ) -> None:
        session = self._core_run()
        replacement = self._replacement()
        with self.assertRaises(ValueError):
            self._replace(self.runner.decide_core(session), replacement)
        state = self.runner.load_state(session)
        state.environment["core_dispatch_pending"] = "inspect"
        self.runner._states.save(state)
        with self.assertRaisesRegex(ValueError, "reconciled before replanning"):
            self._replace(self.runner.decide_core(session), replacement)

    def test_core_replan_persistence_failures_leave_replacements_non_executable(
        self,
    ) -> None:
        for failed_save in (1, 2, 3):
            with self.subTest(failed_save=failed_save):
                session, decision = self._core_review_stop(
                    ActiveEscalationKind.VERIFICATION, "needs_replan"
                )
                replacement = self._replacement()
                save = self.runner._states.save
                saves = 0

                def failing_save(state: TaskState) -> None:
                    nonlocal saves
                    saves += 1
                    if saves == failed_save:
                        raise OSError("controlled failure")
                    save(state)

                with (
                    patch.object(self.runner._states, "save", side_effect=failing_save),
                    self.assertRaises(OSError),
                ):
                    self._replace(decision, replacement)
                parent = self.runner.load_state(session)
                if failed_save == 1:
                    self.assertNotIn("core_stop", parent.environment)
                else:
                    self.assertEqual(
                        self.runner.decide_core(session).outcome, "stopped"
                    )
                for row in self.runner.sessions.list():
                    if row["id"] == session:
                        continue
                    saved = self.runner._states.load(row["id"])
                    if (
                        saved is not None
                        and saved.environment.get("core_replan_origin", {}).get(
                            "parent_session_id"
                        )
                        == session
                    ):
                        with self.assertRaises(ValueError):
                            self.runner.load_state(row["id"])

    def test_core_replan_lineage_missing_parent_scope_and_budget_tamper_fail_closed(
        self,
    ) -> None:
        for kind in ("parent", "scope", "budget", "limits", "link"):
            with self.subTest(kind=kind):
                session, decision = self._core_review_stop(ActiveEscalationKind.POLICY)
                created = self._replace(decision, self._replacement())
                child = self.runner.load_state(created.session_id)
                if kind == "parent":
                    child.environment["core_replan_origin"]["parent_session_id"] = (
                        "missing-parent"
                    )
                elif kind == "scope":
                    child.scope.targets.append("192.0.2.1")
                elif kind == "budget":
                    child.environment["core_budget"]["stage_dispatches"] = 0
                    child.environment["core_budget"]["reserved_steps"] = 0
                elif kind == "limits":
                    child.environment["core_budget"]["limits"][
                        "max_stage_dispatches"
                    ] = 3
                else:
                    parent = self.runner.load_state(session)
                    parent.environment["core_replan_transition"][
                        "replacement_session_id"
                    ] = "foreign-session"
                    self.runner._states.save(parent)
                self.runner._states.save(child)
                with self.assertRaises(ValueError):
                    self.runner.decide_core(child.session_id)

    def test_core_replan_does_not_top_up_an_exhausted_mission(self) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=0, max_reserved_steps=0)
        )
        decision = self.runner.decide_core(session)
        created = self._replace(decision, self._replacement())
        self.assertEqual(
            self.runner.decide_core(created.session_id).outcome, "budget_exhausted"
        )
        executor = AsyncMock()
        asyncio.run(
            self.runner.run_core(self.runner.decide_core(created.session_id), executor)
        )
        executor.assert_not_called()

    def test_core_replan_checks_all_ancestors_and_refuses_cycles(self) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=0, max_reserved_steps=0)
        )
        spec = self._replacement()
        child = self._replace(self.runner.decide_core(session), spec)
        grandchild = self._replace(self.runner.decide_core(child.session_id), spec)
        self.assertEqual(
            self.runner.decide_core(grandchild.session_id).outcome, "budget_exhausted"
        )
        parent = self.runner.load_state(session)
        parent.environment["core_replan_transition"]["replacement_session_id"] = (
            "foreign-session"
        )
        self.runner._states.save(parent)
        with self.assertRaisesRegex(ValueError, "lineage or authority changed"):
            self.runner.load_state(grandchild.session_id)
        child_state = self.runner._states.load(child.session_id)
        child_state.environment["core_replan_origin"]["parent_session_id"] = (
            child.session_id
        )
        self.runner._states.save(child_state)
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.runner.load_state(grandchild.session_id)

    def test_core_replan_lineage_limit_fails_before_stopping_or_creating_run(
        self,
    ) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=0, max_reserved_steps=0)
        )
        spec = self._replacement()
        for _ in range(32):
            session = self._replace(self.runner.decide_core(session), spec).session_id
        decision = self.runner.decide_core(session)
        before = self.runner.load_state(session)
        with self.assertRaisesRegex(ValueError, "bounded to 32"):
            self._replace(decision, spec)
        self.assertEqual(self.runner.load_state(session), before)

    def test_core_replan_cannot_erase_unanswered_input_or_mission_constraints(
        self,
    ) -> None:
        session, _ = self._core_review_stop(ActiveEscalationKind.POLICY)
        state = self.runner.load_state(session)
        state.add_question("human input required")
        state.constraints = ["controlled fixture only"]
        self.runner._states.save(state)
        spec = self._replacement()
        decision = self.runner.decide_core(session)
        with self.assertRaisesRegex(ValueError, "unanswered mission input"):
            self._replace(decision, spec)
        state.resolve_question("human input required")
        self.runner._states.save(state)
        created = self._replace(self.runner.decide_core(session), spec)
        child = self.runner.load_state(created.session_id)
        self.assertEqual(child.constraints, ["controlled fixture only"])
        child.constraints.clear()
        self.runner._states.save(child)
        with self.assertRaisesRegex(ValueError, "lineage or authority changed"):
            self.runner.load_state(child.session_id)

    def test_core_never_claims_extra_mission_criteria_from_stage_completion(
        self,
    ) -> None:
        from decode.planner import CompletionCriterion

        session = self._core_run(independent=True)
        state = self.runner.load_state(session)
        state.completion_conditions = [
            CompletionCriterion(
                kind="at_least", field="successful_actions", expected=100
            )
        ]
        self.runner._states.save(state)
        with patch.object(self.runner.sessions, "close") as close:
            asyncio.run(
                self.runner.run_core(
                    self.runner.decide_core(session), self._typed_executor
                )
            )
            report = asyncio.run(
                self.runner.run_core(
                    self.runner.decide_core(session), self._typed_executor
                )
            )
            self.assertEqual(report.status, "blocked")
            self.assertEqual(self.runner.status(session).status, "blocked")
            close.assert_not_called()
        decision = self.runner.decide_core(session)
        self.assertEqual(decision.outcome, "needs_review")
        replacement = self._replace(decision, self._replacement())
        self.assertEqual(
            self.runner.load_state(replacement.session_id).completion_conditions,
            state.completion_conditions,
        )
        with patch.object(self.runner.sessions, "close") as close:
            report = asyncio.run(
                self.runner.run_core(
                    self.runner.decide_core(replacement.session_id),
                    self._typed_executor,
                )
            )
            self.assertEqual(report.status, "blocked")
            self.assertEqual(
                self.runner.status(replacement.session_id).status, "blocked"
            )
            close.assert_not_called()
        self.assertEqual(
            self.runner.decide_core(replacement.session_id).outcome, "needs_review"
        )

    def test_core_compatibility_completion_respects_extra_mission_criteria(
        self,
    ) -> None:
        from decode.planner import CompletionCriterion

        session = self._core_run(independent=True)
        state = self.runner.load_state(session)
        state.completion_conditions = [
            CompletionCriterion(
                kind="at_least", field="successful_actions", expected=100
            )
        ]
        self.runner._states.save(state)
        with patch.object(self.runner.sessions, "close") as close:
            report = asyncio.run(self.runner.run(session, self._typed_executor))
            self.assertEqual(report.status, "blocked")
            self.assertEqual(self.runner.status(session).status, "blocked")
            close.assert_not_called()
        executor = AsyncMock()
        with self.assertRaisesRegex(ValueError, "Core review stop"):
            asyncio.run(self.runner.run(session, executor))
        executor.assert_not_called()
        self.assertEqual(self.runner.decide_core(session).outcome, "needs_review")

    def _core_review_stop(
        self, kind: ActiveEscalationKind, outcome: str = "blocked"
    ) -> tuple[str, CoreStageDecision]:
        session = self._core_run(
            independent=True,
            budget=CoreMissionBudget(max_stage_dispatches=2, max_reserved_steps=16),
        )

        def stopped(context: WorkflowStageContext) -> StageResult:
            runtime = ActiveStageRuntime(self.runner.load_state(session), context)
            return runtime.finish(
                StageResult(
                    success=False,
                    outcome=outcome,
                    error="token=private-review-secret",
                    final="token=private-review-secret",
                ),
                escalation=kind,
            )

        asyncio.run(self.runner.run_core(self.runner.decide_core(session), stopped))
        return session, self.runner.decide_core(session)

    def test_core_review_classifies_bound_active_causes_without_payloads(self) -> None:
        for kind in ActiveEscalationKind:
            with self.subTest(kind=kind):
                session, decision = self._core_review_stop(kind)
                request = decision.review_request
                self.assertEqual(request.escalation_kind, kind)
                self.assertEqual(request.stage_id, "inspect")
                active = self.runner.load_state(session).active_nodes["inspect"]
                encoded = json.dumps(
                    active.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.assertEqual(
                    request.active_fingerprint,
                    hashlib.sha256(encoded.encode()).hexdigest(),
                )
                self.assertEqual(
                    request.category,
                    "material_replan"
                    if kind is ActiveEscalationKind.MATERIAL_CHANGE
                    else "escalation",
                )
                self.assertNotIn("private-review-secret", decision.model_dump_json())
                self.assertNotIn("private-review-secret", decision.fingerprint())

    def test_core_needs_replan_is_a_request_not_an_applied_plan(self) -> None:
        session, decision = self._core_review_stop(
            ActiveEscalationKind.VERIFICATION, "needs_replan"
        )
        self.assertEqual(decision.review_request.category, "material_replan")
        before = self.runner.load_state(session)
        resolution = CoreReviewResolution(decision=decision, disposition="acknowledged")
        self.runner.review_core(resolution)
        after = self.runner.load_state(session)
        self.assertEqual(after.plan, before.plan)
        self.assertEqual(after.scope, before.scope)
        self.assertEqual(after.active_nodes, before.active_nodes)
        self.assertEqual(
            after.environment["core_budget"], before.environment["core_budget"]
        )
        self.assertEqual(after.actions, before.actions)
        self.assertEqual(after.observations, before.observations)
        self.assertGreater(after.revision, before.revision)
        self.assertEqual(after.status.value, "blocked")
        self.assertEqual(
            CoreReviewResolution.model_validate(
                after.environment["core_review_resolution"]
            ),
            resolution,
        )
        self.assertEqual(self.runner.decide_core(session).outcome, "needs_review")

    def test_core_review_dispositions_never_retry_or_release_independent_work(
        self,
    ) -> None:
        for disposition in ("acknowledged", "rejected"):
            with self.subTest(disposition=disposition):
                session, decision = self._core_review_stop(ActiveEscalationKind.POLICY)
                executor = AsyncMock()
                self.runner.review_core(
                    CoreReviewResolution(decision=decision, disposition=disposition)
                )
                self.assertEqual(
                    self.runner.load_state(session).plan.nodes["finish"].status,
                    "pending",
                )
                next_decision = self.runner.decide_core(session)
                asyncio.run(self.runner.run_core(next_decision, executor))
                executor.assert_not_called()
                self.assertEqual(self._budget(session).stage_dispatches, 1)
                with self.assertRaises(ValueError):
                    asyncio.run(self.runner.run(session, executor))
                executor.assert_not_called()

    def test_core_review_resolution_rejects_stale_altered_and_replayed_requests(
        self,
    ) -> None:
        session, decision = self._core_review_stop(ActiveEscalationKind.DEPENDENCY)
        resolution = CoreReviewResolution(decision=decision, disposition="rejected")
        altered = decision.model_copy(
            update={
                "review_request": decision.review_request.model_copy(
                    update={"active_fingerprint": "a" * 64}
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "stale, altered"):
            self.runner.review_core(
                CoreReviewResolution(decision=altered, disposition="rejected")
            )
        self.runner.review_core(resolution)
        with self.assertRaisesRegex(ValueError, "already consumed"):
            self.runner.review_core(resolution)
        fresh = self.runner.decide_core(session)
        state = self.runner.load_state(session)
        state.scope.targets.append("192.0.2.1")
        self.runner._states.save(state)
        with self.assertRaisesRegex(ValueError, "stale, altered"):
            self.runner.review_core(
                CoreReviewResolution(decision=fresh, disposition="acknowledged")
            )

    def test_core_review_requires_issued_decision_and_trusted_disposition(self) -> None:
        session, decision = self._core_review_stop(ActiveEscalationKind.APPROVAL)
        state = self.runner.load_state(session)
        state.environment.pop("core_decision")
        self.runner._states.save(state)
        with self.assertRaisesRegex(ValueError, "not issued"):
            self.runner.review_core(
                CoreReviewResolution(decision=decision, disposition="acknowledged")
            )
        for updates in (
            {"disposition": "approved"},
            {"approved": True},
            {"scope": ["192.0.2.1"]},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                CoreReviewResolution.model_validate(
                    {
                        "decision": decision.model_dump(),
                        "disposition": "acknowledged",
                        **updates,
                    }
                )
        delegate = self.runner.decide_core(self._core_run())
        with self.assertRaises(ValidationError):
            CoreReviewResolution(decision=delegate, disposition="acknowledged")

    def test_core_review_contract_rejects_unbound_or_inconsistent_causes(self) -> None:
        _, decision = self._core_review_stop(ActiveEscalationKind.POLICY)
        for updates in (
            {"active_fingerprint": ""},
            {"stage_id": ""},
            {"active_outcome": "completed"},
            {"category": "material_replan"},
            {"public_reason": "token=private-review-secret"},
            {"approved": True},
            {"escalation_kind": None},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                CoreReviewRequest.model_validate(
                    {**decision.review_request.model_dump(), **updates}
                )
        delegate = self.runner.decide_core(self._core_run())
        with self.assertRaises(ValidationError):
            CoreStageDecision.model_validate(
                {
                    **delegate.model_dump(),
                    "review_request": decision.review_request.model_dump(),
                }
            )

    def test_core_review_failure_save_is_fail_closed(self) -> None:
        session, decision = self._core_review_stop(ActiveEscalationKind.CANCELLATION)
        before = self.runner.load_state(session)
        with patch.object(
            self.runner._states, "save", side_effect=OSError("controlled failure")
        ):
            with self.assertRaises(OSError):
                self.runner.review_core(
                    CoreReviewResolution(decision=decision, disposition="acknowledged")
                )
        self.assertEqual(self.runner.load_state(session), before)
        executor = AsyncMock()
        asyncio.run(self.runner.run_core(decision, executor))
        executor.assert_not_called()

    def test_core_review_unbound_active_or_missing_proof_stays_unclassified(
        self,
    ) -> None:
        for missing in (False, True):
            with self.subTest(missing=missing):
                session, _ = self._core_review_stop(ActiveEscalationKind.POLICY)
                state = self.runner.load_state(session)
                if missing:
                    state.active_nodes.clear()
                else:
                    state.active_nodes["inspect"] = state.active_nodes[
                        "inspect"
                    ].model_copy(update={"node_fingerprint": "a" * 64})
                self.runner._states.save(state)
                decision = self.runner.decide_core(session)
                self.assertEqual(decision.review_request.category, "review")
                self.assertIsNone(decision.review_request.escalation_kind)
                self.assertEqual(decision.review_request.active_fingerprint, "")

    def test_core_review_budget_failure_and_questions_remain_stopped(self) -> None:
        for cause in ("budget", "failure", "questions"):
            with self.subTest(cause=cause):
                session = self._core_run(
                    budget=CoreMissionBudget(
                        max_stage_dispatches=0, max_reserved_steps=0
                    )
                    if cause == "budget"
                    else None
                )
                state = self.runner.load_state(session)
                if cause == "failure":
                    state.mark("failed")
                elif cause == "questions":
                    state.add_question("token=private-review-secret")
                self.runner._states.save(state)
                decision = self.runner.decide_core(session)
                self.assertEqual(decision.review_request.category, "review")
                self.runner.review_core(
                    CoreReviewResolution(decision=decision, disposition="acknowledged")
                )
                fresh = self.runner.decide_core(session)
                self.assertEqual(fresh.outcome, decision.outcome)
                executor = AsyncMock()
                with self.assertRaises(ValueError):
                    asyncio.run(self.runner.run(session, executor))
                executor.assert_not_called()

    def test_core_review_rejects_malformed_saved_resolution_and_changed_definition(
        self,
    ) -> None:
        session, decision = self._core_review_stop(ActiveEscalationKind.TIMEOUT)
        self.runner.review_core(
            CoreReviewResolution(decision=decision, disposition="rejected")
        )
        state = self.runner.load_state(session)
        state.environment["core_review_resolution"]["disposition"] = "approved"
        self.runner._states.save(state)
        with self.assertRaises(ValidationError):
            self.runner.load_state(session)
        session, decision = self._core_review_stop(ActiveEscalationKind.TIMEOUT)
        self.runner.registry.spec.stage("inspect").max_steps = 9
        with self.assertRaisesRegex(ValueError, "definition changed"):
            self.runner.review_core(
                CoreReviewResolution(decision=decision, disposition="rejected")
            )

    def test_unbudgeted_core_review_cannot_bypass_through_compatibility_run(
        self,
    ) -> None:
        session = self._core_run(independent=True)
        asyncio.run(
            self.runner.run_core(self.runner.decide_core(session), self._executor)
        )
        executor = AsyncMock()
        with self.assertRaisesRegex(ValueError, "review stop cannot be bypassed"):
            asyncio.run(self.runner.run(session, executor))
        executor.assert_not_called()

    def test_core_interrupted_review_never_clears_pending_dispatch(self) -> None:
        session = self._core_run()
        state = self.runner.load_state(session)
        state.environment["core_dispatch_pending"] = "inspect"
        self.runner._states.save(state)
        decision = self.runner.decide_core(session)
        self.assertEqual(decision.review_request.category, "review")
        self.runner.review_core(
            CoreReviewResolution(decision=decision, disposition="acknowledged")
        )
        self.assertEqual(
            self.runner.load_state(session).environment["core_dispatch_pending"],
            "inspect",
        )
        executor = AsyncMock()
        asyncio.run(self.runner.run_core(self.runner.decide_core(session), executor))
        with self.assertRaisesRegex(ValueError, "interrupted Core handoff"):
            asyncio.run(self.runner.run(session, executor))
        executor.assert_not_called()

    def test_core_saved_review_disposition_changes_invalidate_fresh_decisions(
        self,
    ) -> None:
        session, decision = self._core_review_stop(ActiveEscalationKind.SAFETY)
        self.runner.review_core(
            CoreReviewResolution(decision=decision, disposition="acknowledged")
        )
        fresh = self.runner.decide_core(session)
        state = self.runner.load_state(session)
        state.environment["core_review_resolution"]["disposition"] = "rejected"
        self.runner._states.save(state)
        with self.assertRaisesRegex(ValueError, "stale, altered"):
            self.runner.review_core(
                CoreReviewResolution(decision=fresh, disposition="acknowledged")
            )
        state.environment["core_review_resolution"]["decision"]["session_id"] = (
            "foreign-session"
        )
        self.runner._states.save(state)
        with self.assertRaisesRegex(ValueError, "matching mission provenance"):
            self.runner.load_state(session)

    def test_core_failed_active_review_retains_failure_without_replay(self) -> None:
        session, decision = self._core_review_stop(
            ActiveEscalationKind.EXECUTION, "failed"
        )
        self.assertEqual(decision.outcome, "failed")
        self.assertEqual(decision.review_request.category, "escalation")
        report = self.runner.review_core(
            CoreReviewResolution(decision=decision, disposition="rejected")
        )
        self.assertEqual(report.status, "failed")
        self.assertEqual(
            self.runner.load_state(session).plan.nodes["inspect"].status, "error"
        )
        executor = AsyncMock()
        asyncio.run(self.runner.run_core(self.runner.decide_core(session), executor))
        executor.assert_not_called()

    def test_core_zero_or_insufficient_budget_stops_without_handoff(self) -> None:
        for dispatches, steps, reason in (
            (0, 32, "mission stage-dispatch budget exhausted"),
            (1, 7, "mission step-reservation budget cannot cover the next stage"),
        ):
            with self.subTest(dispatches=dispatches, steps=steps):
                session = self._core_run(
                    budget=CoreMissionBudget(
                        max_stage_dispatches=dispatches, max_reserved_steps=steps
                    )
                )
                decision = self.runner.decide_core(session)
                self.assertEqual(decision.outcome, "budget_exhausted")
                self.assertEqual(decision.public_reason, reason)
                self.assertEqual(decision.max_steps, 0)
                executor = AsyncMock()
                report = asyncio.run(self.runner.run_core(decision, executor))
                executor.assert_not_called()
                self.assertEqual(report.status, "blocked")
                state = self.runner.load_state(session)
                self.assertTrue(
                    all(node.status == "pending" for node in state.plan.nodes.values())
                )
                self.assertEqual(state.actions, [])
                self.assertEqual(self._budget(session).reserved_steps, 0)
                self.assertEqual(
                    self.runner.decide_core(session).outcome, "budget_exhausted"
                )

    def test_core_exact_budget_completes_instead_of_reporting_exhaustion(self) -> None:
        session = self._core_run(
            independent=True,
            budget=CoreMissionBudget(max_stage_dispatches=2, max_reserved_steps=16),
        )
        for expected in (8, 16):
            decision = self.runner.decide_core(session)
            report = asyncio.run(self.runner.run_core(decision, self._typed_executor))
            self.assertEqual(self._budget(session).reserved_steps, expected)
        self.assertEqual(report.status, "complete")
        self.assertEqual(self._budget(session).stage_dispatches, 2)
        self.assertEqual(self.runner.decide_core(session).outcome, "complete")

    def test_core_budget_stop_does_not_shrink_gates_or_bypass_dispatch_cap(
        self,
    ) -> None:
        for dispatches, steps, reason in (
            (1, 16, "mission stage-dispatch budget exhausted"),
            (2, 15, "mission step-reservation budget cannot cover the next stage"),
        ):
            with self.subTest(dispatches=dispatches, steps=steps):
                session = self._core_run(
                    independent=True,
                    budget=CoreMissionBudget(
                        max_stage_dispatches=dispatches, max_reserved_steps=steps
                    ),
                )
                first = self.runner.decide_core(session)
                asyncio.run(self.runner.run_core(first, self._typed_executor))
                decision = self.runner.decide_core(session)
                self.assertEqual(decision.outcome, "budget_exhausted")
                self.assertEqual(decision.public_reason, reason)
                self.assertEqual(
                    self.runner.load_state(session)
                    .plan.nodes["finish"]
                    .params["max_steps"],
                    8,
                )
                executor = AsyncMock()
                asyncio.run(self.runner.run_core(decision, executor))
                executor.assert_not_called()
                self.assertEqual(self._budget(session).stage_dispatches, 1)
                self.assertEqual(self._budget(session).reserved_steps, 8)

    def test_core_budget_is_saved_before_execution_and_not_refunded_on_failure(
        self,
    ) -> None:
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                session = self._core_run(
                    budget=CoreMissionBudget(
                        max_stage_dispatches=1, max_reserved_steps=8
                    )
                )
                decision = self.runner.decide_core(session)
                observed: list[tuple[int, int]] = []

                def fail(_context: WorkflowStageContext) -> StageResult:
                    saved = self._budget(session)
                    observed.append((saved.stage_dispatches, saved.reserved_steps))
                    if cancelled:
                        raise asyncio.CancelledError()
                    raise RuntimeError("controlled fixture failure")

                report = asyncio.run(self.runner.run_core(decision, fail))
                self.assertEqual(observed, [(1, 8)])
                self.assertEqual(report.status, "blocked" if cancelled else "failed")
                self.assertEqual(self._budget(session).reserved_steps, 8)
                self.assertEqual(
                    self.runner.decide_core(session).outcome,
                    "needs_review" if cancelled else "failed",
                )

    def test_core_budgeted_mission_cannot_use_unbounded_compatibility_runner(
        self,
    ) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=0, max_reserved_steps=0)
        )
        executor = AsyncMock()
        with self.assertRaisesRegex(ValueError, "bounded run_core"):
            asyncio.run(self.runner.run(session, executor))
        executor.assert_not_called()

    def test_core_human_gate_uses_no_dispatch_budget(self) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=1, max_reserved_steps=8)
        )
        asyncio.run(
            self.runner.run_core(self.runner.decide_core(session), self._typed_executor)
        )
        waiting = self.runner.decide_core(session)
        self.assertEqual(waiting.outcome, "await_approval")
        self.runner.approve_core_stage(waiting)
        self.assertEqual(self._budget(session).stage_dispatches, 1)
        self.assertEqual(self._budget(session).reserved_steps, 8)
        self.assertEqual(self.runner.decide_core(session).outcome, "budget_exhausted")

    def test_core_budget_changes_invalidate_issued_decisions(self) -> None:
        for usage in (False, True):
            with self.subTest(usage=usage):
                session = self._core_run(
                    budget=CoreMissionBudget(
                        max_stage_dispatches=2, max_reserved_steps=16
                    )
                )
                decision = self.runner.decide_core(session)
                state = self.runner.load_state(session)
                if usage:
                    state.environment["core_budget"]["stage_dispatches"] = 1
                    state.environment["core_budget"]["reserved_steps"] = 8
                else:
                    state.environment["core_budget"]["limits"]["max_reserved_steps"] = (
                        17
                    )
                self.runner._states.save(state)
                executor = AsyncMock()
                with self.assertRaisesRegex(
                    ValueError, "stale, altered, or already consumed"
                ):
                    asyncio.run(self.runner.run_core(decision, executor))
                executor.assert_not_called()

    def test_core_malformed_persisted_budget_fails_closed(self) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=1, max_reserved_steps=8)
        )
        decision = self.runner.decide_core(session)
        state = self.runner.load_state(session)
        state.environment["core_budget"]["reserved_steps"] = True
        self.runner._states.save(state)
        executor = AsyncMock()
        with self.assertRaises(ValidationError):
            asyncio.run(self.runner.run_core(decision, executor))
        executor.assert_not_called()

    def test_core_interrupted_dispatch_retains_budget_reservation(self) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=1, max_reserved_steps=8)
        )
        decision = self.runner.decide_core(session)
        executor = AsyncMock()
        with patch.object(
            self.runner,
            "_checkpoint",
            side_effect=OSError("controlled persistence interruption"),
        ):
            with self.assertRaises(OSError):
                asyncio.run(self.runner.run_core(decision, executor))
        executor.assert_not_called()
        self.assertEqual(self._budget(session).reserved_steps, 8)
        self.assertEqual(self.runner.decide_core(session).outcome, "needs_review")

    def test_active_cannot_refund_or_expand_the_mission_budget(self) -> None:
        session = self._core_run(
            budget=CoreMissionBudget(max_stage_dispatches=1, max_reserved_steps=8)
        )
        decision = self.runner.decide_core(session)
        bound: list[TaskState] = []
        outer = self

        class RefundExecutor:
            def bind_state(self, state: TaskState) -> None:
                bound.append(state)

            def __call__(self, context: WorkflowStageContext) -> StageResult:
                result = outer._typed_executor(context)
                bound[0].environment["core_budget"]["reserved_steps"] = 0
                bound[0].environment["core_budget"]["limits"][
                    "max_stage_dispatches"
                ] = 1024
                return result

        report = asyncio.run(self.runner.run_core(decision, RefundExecutor()))
        self.assertEqual(report.status, "blocked")
        budget = self._budget(session)
        self.assertEqual(budget.limits.max_stage_dispatches, 1)
        self.assertEqual(budget.stage_dispatches, 1)
        self.assertEqual(budget.reserved_steps, 8)

    def _typed_executor(self, context: WorkflowStageContext) -> StageResult:
        state = self.runner.load_state(context.session_id)
        observation = ActiveObservation(
            request_id=f"fixture-{context.stage.id}",
            capability="file_read",
            provider="local",
            status="success",
            success=True,
            evidence_id=f"controlled-{context.stage.id}",
            evidence_hash="a" * 64,
        )
        return StageResult(
            success=True,
            final="controlled result",
            successful_actions=1,
            evidence=[
                EvidenceLink(
                    id=observation.evidence_id, sha256=observation.evidence_hash
                )
            ],
            active=ActiveNodeResult(
                session_id=state.session_id,
                node_id=context.stage.id,
                workflow_fingerprint=state.environment["workflow_fingerprint"],
                node_fingerprint=state.plan.nodes[
                    context.stage.id
                ].material_fingerprint(),
                outcome="completed",
                gate_passed=True,
                attempts=1,
                observations=(observation,),
            ),
        )

    def test_core_decision_is_persisted_without_execution_and_is_strict(self) -> None:
        session = self._core_run()
        before = self.runner.load_state(session)
        decision = self.runner.decide_core(session)
        after = self.runner.load_state(session)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(decision.state_version, after.revision)
        self.assertEqual(decision.outcome, "delegate")
        self.assertEqual(decision.stage_id, "inspect")
        self.assertEqual(
            after.environment["core_decision"], decision.model_dump(mode="json")
        )
        self.assertEqual(after.actions, [])
        self.assertNotIn("controlled fixtures", decision.model_dump_json())
        for updates in (
            {"approved": True},
            {"provider": "remote"},
            {"max_steps": 0},
            {"state_version": True},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                CoreStageDecision.model_validate({**decision.model_dump(), **updates})

    def test_core_delegates_one_stage_then_requires_fresh_decision(self) -> None:
        session = self._core_run(independent=True)
        decision = self.runner.decide_core(session)
        calls: list[str] = []

        def execute(context: WorkflowStageContext) -> StageResult:
            calls.append(context.stage.id)
            return self._typed_executor(context)

        report = asyncio.run(self.runner.run_core(decision, execute))
        self.assertEqual(calls, ["inspect"])
        self.assertEqual(report.completed, ["inspect"])
        self.assertEqual(report.ready, ["finish"])
        self.assertEqual(report.status, "investigating")
        with self.assertRaisesRegex(ValueError, "stale, altered, or already consumed"):
            asyncio.run(self.runner.run_core(decision, execute))
        next_decision = self.runner.decide_core(session)
        self.assertGreater(next_decision.state_version, decision.state_version)
        self.assertEqual(next_decision.stage_id, "finish")
        report = asyncio.run(self.runner.run_core(next_decision, execute))
        self.assertEqual(report.status, "complete")
        completed = self.runner.decide_core(session)
        self.assertEqual(completed.outcome, "complete")
        executor = AsyncMock()
        asyncio.run(self.runner.run_core(completed, executor))
        executor.assert_not_called()

    def test_core_decision_rejects_state_changes_even_without_revision_bump(
        self,
    ) -> None:
        for change in ("scope", "provider", "target", "revision", "question"):
            with self.subTest(change=change):
                session = self._core_run()
                decision = self.runner.decide_core(session)
                state = self.runner.load_state(session)
                if change == "scope":
                    state.scope.read_roots.append(str(Path(self.directory.name)))
                elif change == "provider":
                    state.environment["provider"] = "changed-provider"
                elif change == "target":
                    state.environment["target"] = "192.0.2.1"
                elif change == "revision":
                    state._touch()
                else:
                    state.add_question("human input required")
                self.runner._states.save(state)
                executor = AsyncMock()
                with self.assertRaisesRegex(
                    ValueError, "stale, altered, or already consumed"
                ):
                    asyncio.run(self.runner.run_core(decision, executor))
                executor.assert_not_called()

    def test_core_rejects_unissued_or_altered_decision_and_compatibility_task(
        self,
    ) -> None:
        session = self._core_run()
        state = self.runner.load_state(session)
        unissued = CoreWorkflowPlanner(self.runner.registry).decide(
            state, self.runner.registry.spec
        )
        executor = AsyncMock()
        with self.assertRaisesRegex(ValueError, "not issued"):
            asyncio.run(self.runner.run_core(unissued, executor))
        decision = self.runner.decide_core(session)
        for updates in (
            {"max_steps": decision.max_steps + 1},
            {"stage_id": "finish"},
            {"state_fingerprint": "f" * 64},
        ):
            with (
                self.subTest(updates=updates),
                self.assertRaisesRegex(
                    ValueError, "stale, altered, or already consumed"
                ),
            ):
                asyncio.run(
                    self.runner.run_core(decision.model_copy(update=updates), executor)
                )
        executor.assert_not_called()
        legacy = self.runner.start("test-flow", "compatibility task")
        with self.assertRaises(ValueError):
            self.runner.decide_core(legacy.session_id)

    def test_core_human_gate_cannot_delegate_or_approve_agent_work(self) -> None:
        session = self._core_run()
        first = self.runner.decide_core(session)
        with self.assertRaisesRegex(ValueError, "awaiting-human"):
            self.runner.approve_core_stage(first)
        asyncio.run(self.runner.run_core(first, self._typed_executor))
        waiting = self.runner.decide_core(session)
        self.assertEqual(waiting.outcome, "await_approval")
        self.assertEqual(waiting.max_steps, 0)
        executor = AsyncMock()
        report = asyncio.run(self.runner.run_core(waiting, executor))
        executor.assert_not_called()
        self.assertEqual(report.needs_review, ["approve"])
        fresh = self.runner.decide_core(session)
        report = self.runner.approve_core_stage(fresh)
        self.assertEqual(report.completed, ["inspect", "approve"])
        self.assertEqual(report.ready, ["finish"])
        self.assertEqual(self.runner.decide_core(session).stage_id, "finish")

    def test_core_interrupted_consumption_never_replays_pending_stage(self) -> None:
        session = self._core_run()
        decision = self.runner.decide_core(session)
        state = self.runner.load_state(session)
        state.environment["core_decision_consumed"] = True
        state.environment["core_dispatch_pending"] = "inspect"
        self.runner._states.save(state)
        executor = AsyncMock()
        with self.assertRaises(ValueError):
            asyncio.run(self.runner.run_core(decision, executor))
        fresh = self.runner.decide_core(session)
        self.assertEqual(fresh.outcome, "needs_review")
        report = asyncio.run(self.runner.run_core(fresh, executor))
        self.assertEqual(report.status, "blocked")
        with self.assertRaisesRegex(ValueError, "interrupted Core handoff"):
            asyncio.run(self.runner.run(session, executor))
        executor.assert_not_called()

    def test_core_stops_untyped_completion_and_does_not_delegate_dependents(
        self,
    ) -> None:
        session = self._core_run()
        first = self.runner.decide_core(session)
        report = asyncio.run(self.runner.run_core(first, self._executor))
        self.assertEqual(report.status, "blocked")
        state = self.runner.load_state(session)
        self.assertEqual(state.active_nodes["inspect"].outcome.value, "needs_replan")
        self.assertEqual(state.plan.nodes["approve"].status, "pending")
        self.assertEqual(self.runner.decide_core(session).outcome, "needs_review")

    def test_core_refuses_unverified_compatibility_completion(self) -> None:
        session = self._core_run()
        asyncio.run(self.runner.run(session, self._executor))
        decision = self.runner.decide_core(session)
        self.assertEqual(decision.outcome, "needs_review")
        self.assertEqual(
            decision.public_reason, "completed work lacks bound Active verification"
        )

    def test_core_cancellation_is_checkpointed_without_replay(self) -> None:
        session = self._core_run()
        first = self.runner.decide_core(session)

        async def cancel(_context: WorkflowStageContext) -> StageResult:
            raise asyncio.CancelledError()

        report = asyncio.run(self.runner.run_core(first, cancel))
        self.assertEqual(report.status, "blocked")
        active = self.runner.load_state(session).active_nodes["inspect"]
        self.assertEqual(active.escalation.kind, ActiveEscalationKind.CANCELLATION)
        self.assertEqual(self.runner.decide_core(session).outcome, "needs_review")

    def test_core_failure_and_unknown_questions_do_not_invoke_executor(self) -> None:
        for failed in (False, True):
            with self.subTest(failed=failed):
                session = self._core_run()
                state = self.runner.load_state(session)
                if failed:
                    state.mark("failed")
                else:
                    state.add_question("human input required")
                self.runner._states.save(state)
                decision = self.runner.decide_core(session)
                self.assertEqual(
                    decision.outcome, "failed" if failed else "needs_review"
                )
                executor = AsyncMock()
                asyncio.run(self.runner.run_core(decision, executor))
                executor.assert_not_called()

    def test_core_mandatory_persistence_failure_stops_before_handoff(self) -> None:
        session = self._core_run()
        decision = self.runner.decide_core(session)
        executor = AsyncMock()
        with patch.object(
            self.runner._states, "save", side_effect=OSError("controlled failure")
        ):
            with self.assertRaises(OSError):
                asyncio.run(self.runner.run_core(decision, executor))
        executor.assert_not_called()

    def test_core_rejects_active_result_above_delegated_step_bounds(self) -> None:
        session = self._core_run()
        decision = self.runner.decide_core(session)

        def excessive(context: WorkflowStageContext) -> StageResult:
            result = self._typed_executor(context)
            result.active = result.active.model_copy(
                update={"attempts": decision.max_steps + 1}
            )
            return result

        report = asyncio.run(self.runner.run_core(decision, excessive))
        self.assertEqual(report.status, "blocked")
        self.assertEqual(
            self.runner.load_state(session).active_nodes["inspect"].escalation.kind,
            ActiveEscalationKind.BUDGET,
        )

    def test_core_rejects_envelope_mutation_even_with_typed_completion(self) -> None:
        session = self._core_run()
        decision = self.runner.decide_core(session)
        bound: list[TaskState] = []

        class MutatingExecutor:
            def bind_state(self, state: TaskState) -> None:
                bound.append(state)

            def __call__(self, context: WorkflowStageContext) -> StageResult:
                bound[0].scope.targets.append("192.0.2.1")
                return outer._typed_executor(context)

        outer = self
        report = asyncio.run(self.runner.run_core(decision, MutatingExecutor()))
        self.assertEqual(report.status, "blocked")
        self.assertEqual(
            self.runner.load_state(session).active_nodes["inspect"].escalation.kind,
            ActiveEscalationKind.MATERIAL_CHANGE,
        )
        self.assertEqual(self.runner.load_state(session).scope.targets, [])

    def test_core_callback_cannot_rewrite_authority_other_nodes_or_mission_guards(
        self,
    ) -> None:
        for field in ("scope", "selection", "constraints", "criteria", "plan", "stop"):
            with self.subTest(field=field):
                session = self._core_run(independent=True)
                before = self.runner.load_state(session)
                outer = self

                class MutatingExecutor:
                    def bind_state(self, state: TaskState) -> None:
                        self.state = state

                    def __call__(self, context: WorkflowStageContext) -> StageResult:
                        if field == "scope":
                            self.state.scope.targets.append("192.0.2.1")
                        elif field == "selection":
                            self.state.environment.pop("core_selection")
                        elif field == "constraints":
                            self.state.constraints.append("changed restriction")
                        elif field == "criteria":
                            from decode.planner import CompletionCriterion

                            self.state.completion_conditions.append(
                                CompletionCriterion(kind="present", field="result")
                            )
                        elif field == "plan":
                            self.state.plan.nodes["finish"].status = "success"
                        else:
                            self.state.environment["core_stop"] = {}
                        return outer._typed_executor(context)

                asyncio.run(
                    self.runner.run_core(
                        self.runner.decide_core(session), MutatingExecutor()
                    )
                )
                after = self.runner.load_state(session)
                self.assertEqual(
                    after.active_nodes["inspect"].escalation.kind,
                    ActiveEscalationKind.MATERIAL_CHANGE,
                )
                self.assertEqual(after.scope, before.scope)
                self.assertEqual(after.constraints, before.constraints)
                self.assertEqual(
                    after.completion_conditions, before.completion_conditions
                )
                self.assertEqual(after.plan.nodes["finish"].status, "pending")
                self.assertNotIn("core_stop", after.environment)
                self.assertEqual(
                    after.environment["core_selection"],
                    before.environment["core_selection"],
                )

    def test_core_context_mutation_cannot_replace_reviewed_stage_gates(self) -> None:
        session = self._core_run()
        decision = self.runner.decide_core(session)

        def changed(context: WorkflowStageContext) -> StageResult:
            result = self._typed_executor(context)
            context.stage.gate.min_successful_actions = 0
            return result

        report = asyncio.run(self.runner.run_core(decision, changed))
        self.assertEqual(report.status, "blocked")
        state = self.runner._states.load(session)
        self.assertEqual(
            state.active_nodes["inspect"].escalation.kind,
            ActiveEscalationKind.MATERIAL_CHANGE,
        )

    def test_core_start_persists_selection_without_executing_or_granting_scope(
        self,
    ) -> None:
        spec = self.runner.registry.spec
        intent = CoreIntent(objective="inspect the workflow", mode="hybrid")
        with patch.object(self.runner, "run", new_callable=AsyncMock) as execute:
            created = self.runner.start_core(
                intent, (CoreWorkflowPlannerTest._review(spec),)
            )
        execute.assert_not_called()
        state = self.runner.load_state(created.session_id)
        selection = CoreWorkflowSelection.model_validate(
            state.environment["core_selection"]
        )
        self.assertEqual(selection.intent_fingerprint, intent.fingerprint())
        self.assertEqual(selection.criteria["inspect"], spec.stage("inspect").gate)
        self.assertEqual(state.scope.read_roots, [])
        self.assertEqual(state.scope.write_roots, [])
        self.assertEqual(state.scope.targets, [])
        self.assertFalse(state.scope.allow_destructive)
        self.assertEqual(state.actions, [])
        self.assertEqual(state.observations, [])
        self.assertEqual(created.ready, ["inspect"])
        self.assertTrue(
            all(node.status == "pending" for node in state.plan.nodes.values())
        )

    def test_core_refusal_creates_no_session(self) -> None:
        with self.assertRaisesRegex(ValueError, "no reviewed workflow"):
            self.runner.start_core(CoreIntent(objective="inspect", mode="hybrid"), ())
        self.assertEqual(self.runner.sessions.list(), [])
        spec = self.runner.registry.spec
        spec.target_required = True
        with self.assertRaisesRegex(ValueError, "explicit target"):
            self.runner.start_core(
                CoreIntent(objective="inspect", mode="hybrid"),
                (CoreWorkflowPlannerTest._review(spec),),
            )
        self.assertEqual(self.runner.sessions.list(), [])

    def test_core_redacts_objective_in_session_and_saved_decision(self) -> None:
        spec = self.runner.registry.spec
        created = self.runner.start_core(
            CoreIntent(
                objective="inspect token=private-objective-secret", mode="hybrid"
            ),
            (CoreWorkflowPlannerTest._review(spec),),
        )
        self.assertNotIn(
            "private-objective-secret",
            json.dumps(self.runner.sessions.get(created.session_id)),
        )
        self.assertNotIn(
            "private-objective-secret", self.store.load_task_state(created.session_id)
        )
        self.runner.load_state(created.session_id)

    def test_core_detects_selection_or_graph_changes_before_executor(self) -> None:
        spec = self.runner.registry.spec
        for change in ("criteria", "objective", "dependencies", "attempts"):
            with self.subTest(change=change):
                created = self.runner.start_core(
                    CoreIntent(objective="inspect", mode="hybrid"),
                    (CoreWorkflowPlannerTest._review(spec),),
                )
                state = self.runner.load_state(created.session_id)
                if change == "criteria":
                    state.environment["core_selection"]["criteria"]["inspect"][
                        "require_evidence"
                    ] = False
                elif change == "objective":
                    state.objective = "different objective"
                elif change == "dependencies":
                    state.plan.nodes["finish"].depends_on = []
                else:
                    state.plan.nodes["inspect"].max_attempts = 3
                self.runner._states.save(state)
                self.runner._save_plan(state)
                executor = AsyncMock()
                with self.assertRaisesRegex(
                    ValueError, "Core selection no longer matches"
                ):
                    asyncio.run(self.runner.run(created.session_id, executor))
                executor.assert_not_called()

    def test_core_creation_rechecks_changed_registry(self) -> None:
        spec = self.runner.registry.spec
        changed = spec.model_copy(deep=True)
        changed.guidance = "changed between selection and compilation"
        with patch.object(self.runner.registry, "get", side_effect=[spec, changed]):
            with self.assertRaisesRegex(ValueError, "changed before plan creation"):
                self.runner.start_core(
                    CoreIntent(objective="inspect", mode="hybrid"),
                    (CoreWorkflowPlannerTest._review(spec),),
                )
        self.assertEqual(self.runner.sessions.list(), [])

    def test_core_selected_run_preserves_human_gate_and_safe_resume(self) -> None:
        spec = self.runner.registry.spec
        created = self.runner.start_core(
            CoreIntent(objective="inspect", mode="hybrid"),
            (CoreWorkflowPlannerTest._review(spec),),
        )
        paused = asyncio.run(self.runner.run(created.session_id, self._typed_executor))
        self.assertEqual(paused.needs_review, ["approve"])
        executor = AsyncMock()
        still_paused = asyncio.run(self.runner.run(created.session_id, executor))
        executor.assert_not_called()
        self.assertEqual(still_paused.status, "blocked")
        complete = asyncio.run(
            self.runner.run(
                created.session_id, self._typed_executor, approve_stage="approve"
            )
        )
        self.assertEqual(complete.status, "complete")

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


class CoreCLITest(unittest.TestCase):
    _core_run = WorkflowRunnerTest._core_run
    _core_review_stop = WorkflowRunnerTest._core_review_stop
    _replacement = WorkflowRunnerTest._replacement
    _typed_executor = WorkflowRunnerTest._typed_executor

    def setUp(self) -> None:
        from typer.testing import CliRunner

        from decode.app.config import Config
        from decode.bootstrap.engine import BootstrapEngine

        WorkflowRunnerTest.setUp(self)
        root = Path(self.directory.name)
        with (
            patch("decode.persistence.create_store", return_value=self.store),
            patch(
                "decode.bootstrap.engine.BootstrapEngine",
                return_value=BootstrapEngine(root / "bootstrap"),
            ),
            patch.multiple(
                Config,
                LOGS_PATH=root / "logs",
                AUDIT_PATH=root / "audit",
                FEEDBACK_PATH=root / "feedback",
            ),
        ):
            self.cli = importlib.import_module("decode.app.cli")
        self.cli_runner = CliRunner()

    def tearDown(self) -> None:
        WorkflowRunnerTest.tearDown(self)

    def _invoke(self, *args: str) -> Any:
        with patch.object(self.cli, "_workflow_runner", return_value=self.runner):
            return self.cli_runner.invoke(self.cli.app, ["core", *args])

    def _pin(self, spec: WorkflowSpec | None = None) -> str:
        spec = spec or self.runner.registry.spec
        return f"{spec.name}@{spec.version}:{spec.fingerprint()}"

    def _start(self) -> str:
        result = self._invoke(
            "start",
            "--goal",
            "inspect controlled fixtures",
            "--intent-mode",
            "hybrid",
            "--reviewed",
            self._pin(),
            "--max-stage-dispatches",
            "2",
            "--max-reserved-steps",
            "16",
        )
        self.assertEqual(result.exit_code, 0, result.output)
        return json.loads(result.output)["session_id"]

    def _decision_id(self, session: str) -> str:
        result = self._invoke("decide", session)
        self.assertEqual(result.exit_code, 0, result.output)
        return json.loads(result.output)["decision_id"]

    def test_core_cli_inspection_selection_and_start_are_non_executing(self) -> None:
        with patch.object(self.cli, "_workflow_executor") as factory:
            listing = self._invoke("workflows")
            self.assertEqual(listing.exit_code, 0, listing.output)
            self.assertEqual(json.loads(listing.output)[0]["reviewed_pin"], self._pin())
            selection = self._invoke(
                "select",
                "--goal",
                "inspect",
                "--intent-mode",
                "hybrid",
                "--reviewed",
                self._pin(),
            )
            self.assertEqual(json.loads(selection.output)["outcome"], "selected")
            self.assertEqual(self.runner.sessions.list(), [])
            session = self._start()
            state = self.runner.load_state(session)
            self.assertEqual(state.scope.read_roots, [])
            self.assertEqual(state.scope.write_roots, [])
            self.assertEqual(state.scope.targets, [])
            status = self._invoke("status", session)
            self.assertEqual(
                json.loads(status.output)["strategy"]["policy"],
                "reviewed-declaration-order-v1",
            )
            factory.assert_not_called()

    def test_core_cli_requires_explicit_pins_and_bounded_budget(self) -> None:
        for pin in (None, "malformed", "test-flow@1:" + "a" * 64):
            with self.subTest(pin=pin):
                args = [
                    "start",
                    "--goal",
                    "inspect",
                    "--intent-mode",
                    "hybrid",
                    "--max-stage-dispatches",
                    "1",
                    "--max-reserved-steps",
                    "8",
                ]
                if pin is not None:
                    args.extend(["--reviewed", pin])
                result = self._invoke(*args)
                self.assertEqual(result.exit_code, 1)
                self.assertEqual(self.runner.sessions.list(), [])
        result = self._invoke(
            "start",
            "--goal",
            "inspect",
            "--intent-mode",
            "hybrid",
            "--reviewed",
            self._pin(),
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(self.runner.sessions.list(), [])

    def test_core_cli_advances_one_stage_and_keeps_gate_approval_separate(self) -> None:
        session = self._start()
        identifier = self._decision_id(session)
        with patch.object(
            self.cli, "_workflow_executor", return_value=self._typed_executor
        ) as factory:
            advanced = self._invoke("advance", session, "--decision", identifier)
            self.assertEqual(advanced.exit_code, 0, advanced.output)
            self.assertEqual(json.loads(advanced.output)["completed"], ["inspect"])
            factory.assert_called_once()
            factory.reset_mock()
            replayed = self._invoke("advance", session, "--decision", identifier)
            self.assertEqual(replayed.exit_code, 1)
            factory.assert_not_called()
            identifier = self._decision_id(session)
            approved = self._invoke("approve", session, "--decision", identifier)
            self.assertEqual(approved.exit_code, 0, approved.output)
            factory.assert_not_called()
            self.assertEqual(
                self.runner.load_state(session).plan.nodes["finish"].status, "pending"
            )
            identifier = self._decision_id(session)
            final = self._invoke("advance", session, "--decision", identifier)
            self.assertEqual(json.loads(final.output)["status"], "complete")

    def test_core_cli_review_and_stop_do_not_initialize_model_or_executor(self) -> None:
        session, _ = self._core_review_stop(ActiveEscalationKind.APPROVAL)
        with patch.object(self.cli, "_workflow_executor") as factory:
            identifier = self._decision_id(session)
            reviewed = self._invoke(
                "review",
                session,
                "--decision",
                identifier,
                "--disposition",
                "acknowledged",
            )
            self.assertEqual(reviewed.exit_code, 0, reviewed.output)
            self.assertEqual(json.loads(reviewed.output)["status"], "blocked")
            identifier = self._decision_id(session)
            stopped = self._invoke("stop", session, "--decision", identifier)
            self.assertEqual(stopped.exit_code, 0, stopped.output)
            identifier = self._decision_id(session)
            advanced = self._invoke("advance", session, "--decision", identifier)
            self.assertEqual(advanced.exit_code, 0, advanced.output)
            factory.assert_not_called()
            self.assertEqual(self.runner.decide_core(session).outcome, "stopped")

    def test_core_cli_replan_stops_parent_and_creates_only_pending_replacement(
        self,
    ) -> None:
        session, _ = self._core_review_stop(
            ActiveEscalationKind.VERIFICATION, "needs_replan"
        )
        replacement = self._replacement()
        with patch.object(self.cli, "_workflow_executor") as factory:
            result = self._invoke(
                "replan",
                session,
                "--decision",
                self._decision_id(session),
                "--workflow",
                replacement.name,
                "--reviewed",
                self._pin(replacement),
            )
            self.assertEqual(result.exit_code, 0, result.output)
            child = self.runner.load_state(json.loads(result.output)["session_id"])
            self.assertTrue(
                all(node.status == "pending" for node in child.plan.nodes.values())
            )
            self.assertEqual(child.environment["core_budget"]["stage_dispatches"], 1)
            self.assertEqual(self.runner.decide_core(session).outcome, "stopped")
            factory.assert_not_called()

    def test_core_cli_rejects_stale_changed_scope_before_executor_initialization(
        self,
    ) -> None:
        session = self._start()
        identifier = self._decision_id(session)
        state = self.runner.load_state(session)
        state.scope.targets.append("192.0.2.1")
        self.runner._states.save(state)
        with patch.object(self.cli, "_workflow_executor") as factory:
            result = self._invoke("advance", session, "--decision", identifier)
            self.assertEqual(result.exit_code, 1)
            factory.assert_not_called()

    def test_core_cli_errors_do_not_echo_sensitive_payloads(self) -> None:
        secret = "private-core-error-secret"
        result = self._invoke(
            "start",
            "--goal",
            "inspect",
            "--intent-mode",
            "hybrid",
            "--reviewed",
            f"token={secret}",
            "--max-stage-dispatches",
            "1",
            "--max-reserved-steps",
            "8",
        )
        self.assertEqual(result.exit_code, 1)
        self.assertNotIn(secret, result.output)
        session = self._start()
        for error_type in (OSError, sqlite3.OperationalError):
            for boundary in ("save", "initialization"):
                with self.subTest(error_type=error_type, boundary=boundary):
                    target = self.runner._states if boundary == "save" else self.cli
                    attribute = "save" if boundary == "save" else "_workflow_runner"
                    with patch.object(
                        target, attribute, side_effect=error_type(f"token={secret}")
                    ):
                        result = (
                            self._invoke("decide", session)
                            if boundary == "save"
                            else self.cli_runner.invoke(
                                self.cli.app, ["core", "decide", session]
                            )
                        )
                    self.assertEqual(result.exit_code, 1)
                    self.assertNotIn(secret, result.output)
                    self.assertEqual(
                        json.loads(result.output)["error"], "core_request_rejected"
                    )

    def test_core_cli_help_exposes_only_explicit_operator_controls(self) -> None:
        for command in (
            "workflows",
            "select",
            "start",
            "status",
            "decide",
            "advance",
            "approve",
            "review",
            "stop",
            "replan",
        ):
            with self.subTest(command=command):
                result = self._invoke(command, "--help")
                self.assertEqual(result.exit_code, 0, result.output)


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

    def test_core_selected_stage_uses_governance_with_and_without_model(self) -> None:
        path = self.root / "core-read.txt"
        content = "controlled Core fixture"
        path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode()).hexdigest()
        for model in (False, True):
            with self.subTest(model=model):
                runner = self._runner(
                    expected_file_sha256=digest, expected_file_path=str(path)
                )
                created = runner.start_core(
                    CoreIntent(objective="inspect", mode="hybrid"),
                    (CoreWorkflowPlannerTest._review(runner.registry.spec),),
                    read_roots=[str(self.root)],
                    budget=CoreMissionBudget(
                        max_stage_dispatches=1, max_reserved_steps=8
                    ),
                )
                executor = (
                    self._model_executor(runner, created.session_id, path)
                    if model
                    else self._executor(runner, created.session_id, path)
                )
                decision = runner.decide_core(created.session_id)
                report = asyncio.run(runner.run_core(decision, executor))
                self.assertEqual(report.status, "complete")
                budget = CoreBudgetState.model_validate(
                    runner.load_state(created.session_id).environment["core_budget"]
                )
                self.assertEqual(
                    (budget.stage_dispatches, budget.reserved_steps), (1, 8)
                )
                active = runner.load_state(created.session_id).active_nodes["inspect"]
                self.assertTrue(active.gate_passed)
                self.assertEqual(active.observations[0].signals["file_sha256"], digest)
                self.assertTrue(active.observations[0].evidence_hash)
                self.assertTrue(self.audit.query(event_type="tool_execution"))
                coordinator = (
                    executor._agent._coordinator if model else executor._coordinator
                )
                self.assertTrue(coordinator._logging.get_logs(tool_filter="file_read"))
                self.assertTrue(
                    coordinator._feedback.get_execution_feedback("file_read")
                )

    def test_mission_budget_stop_does_not_invoke_active_or_model(self) -> None:
        path = self.root / "budget-controlled.txt"
        path.write_text("controlled fixture", encoding="utf-8")
        for model in (False, True):
            with self.subTest(model=model):
                runner = self._runner()
                created = runner.start_core(
                    CoreIntent(objective="inspect", mode="hybrid"),
                    (CoreWorkflowPlannerTest._review(runner.registry.spec),),
                    read_roots=[str(self.root)],
                    budget=CoreMissionBudget(
                        max_stage_dispatches=0, max_reserved_steps=0
                    ),
                )
                executor = (
                    self._model_executor(runner, created.session_id, path)
                    if model
                    else self._executor(runner, created.session_id, path)
                )
                if model:
                    executor._agent.llm.chat = AsyncMock()
                else:
                    executor._host.run = AsyncMock()
                decision = runner.decide_core(created.session_id)
                self.assertEqual(decision.outcome, "budget_exhausted")
                report = asyncio.run(runner.run_core(decision, executor))
                self.assertEqual(report.status, "blocked")
                if model:
                    executor._agent.llm.chat.assert_not_awaited()
                else:
                    executor._host.run.assert_not_awaited()
                self.assertEqual(runner.load_state(created.session_id).active_nodes, {})

    def test_core_review_pin_cannot_authorize_an_unscoped_read(self) -> None:
        path = self.root / "core-denied.txt"
        path.write_text("controlled fixture", encoding="utf-8")
        runner = self._runner()
        created = runner.start_core(
            CoreIntent(objective="inspect", mode="hybrid"),
            (CoreWorkflowPlannerTest._review(runner.registry.spec),),
        )
        executor = self._executor(runner, created.session_id, path)
        original_read = Path.read_bytes
        file_reads: list[Path] = []

        def guarded_read(candidate: Path) -> bytes:
            if candidate == path:
                file_reads.append(candidate)
            return original_read(candidate)

        with patch("decode.hostcontrol.operations.Path.read_bytes", new=guarded_read):
            decision = runner.decide_core(created.session_id)
            report = asyncio.run(runner.run_core(decision, executor))
        self.assertEqual(file_reads, [])
        self.assertNotEqual(report.status, "complete")
        active = runner.load_state(created.session_id).active_nodes["inspect"]
        self.assertFalse(active.observations[0].success)
        self.assertEqual(active.observations[0].error_category, "execution_failure")
        self.assertEqual(active.observations[0].signals, {})
        self.assertFalse(active.gate_passed)
        self.assertTrue(
            executor._coordinator._logging.get_logs(tool_filter="file_read")
        )
        self.assertTrue(
            executor._coordinator._feedback.get_execution_feedback("file_read")
        )
        review = runner.decide_core(created.session_id)
        self.assertEqual(review.review_request.escalation_kind, active.escalation.kind)
        before = runner.load_state(created.session_id)
        runner.review_core(
            CoreReviewResolution(decision=review, disposition="acknowledged")
        )
        after = runner.load_state(created.session_id)
        self.assertEqual(after.scope, before.scope)
        self.assertEqual(after.active_nodes, before.active_nodes)
        host_calls = AsyncMock()
        with patch.object(executor._host, "run", host_calls):
            asyncio.run(
                runner.run_core(runner.decide_core(created.session_id), executor)
            )
            host_calls.assert_not_awaited()
            with self.assertRaisesRegex(ValueError, "review stop cannot be bypassed"):
                asyncio.run(runner.run(created.session_id, executor))
            host_calls.assert_not_awaited()

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
                created = runner.start_core(
                    CoreIntent(objective="inspect", mode="hybrid"),
                    (CoreWorkflowPlannerTest._review(runner.registry.spec),),
                    read_roots=[str(self.root)],
                    budget=CoreMissionBudget(
                        max_stage_dispatches=1, max_reserved_steps=8
                    ),
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
                decision = runner.decide_core(created.session_id)
                report = asyncio.run(runner.run_core(decision, executor))
                self.assertEqual(report.status, "complete", report.message)
                state = runner.load_state(created.session_id)
                self.assertEqual(
                    state.environment["core_selection"]["outcome"], "selected"
                )
                self.assertEqual(
                    state.environment["core_strategy"]["policy"],
                    "reviewed-declaration-order-v1",
                )
                self.assertEqual(
                    state.environment["core_budget"]["stage_dispatches"], 1
                )
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
                with self.assertRaises(ValueError):
                    asyncio.run(runner.run_core(decision, executor))
                replayed = asyncio.run(
                    runner.run_core(runner.decide_core(created.session_id), executor)
                )
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
