"""Discovery for declarative workflows embedded in markdown playbooks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from ..schema import ActiveEscalationKind, ActiveOutcome, TaskState, TaskStatus
from ..skills.markdown_skill import playbook_directories, split_frontmatter
from .models import (
    CoreBudgetState,
    CoreIntent,
    CoreMissionStop,
    CoreReviewRequest,
    CoreStageDecision,
    CoreStrategy,
    CoreWorkflowSelection,
    ReviewedWorkflow,
    StageExecution,
    WorkflowSpec,
    core_state_fingerprint,
)


def parse_workflow(
    text: str, *, fallback_name: str, source: str = ""
) -> WorkflowSpec | None:
    frontmatter, body = split_frontmatter(text)
    if not frontmatter.strip():
        return None
    meta = yaml.safe_load(frontmatter)
    if not isinstance(meta, dict) or not isinstance(meta.get("workflow"), dict):
        return None
    workflow: dict[str, Any] = dict(meta["workflow"])
    workflow.setdefault("name", str(meta.get("name") or fallback_name))
    workflow.setdefault("description", str(meta.get("description") or ""))
    workflow.setdefault("target_required", bool(meta.get("target_required", False)))
    workflow["guidance"] = body.strip()
    workflow["source"] = source
    return WorkflowSpec.model_validate(workflow)


def load_workflow(path: Path) -> WorkflowSpec | None:
    return parse_workflow(
        path.read_text(encoding="utf-8"),
        fallback_name=path.stem,
        source=str(path),
    )


class WorkflowRegistry:
    """A small interface over packaged and configured workflow manifests."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowSpec] = {}
        self._load()

    def _load(self) -> None:
        for directory in playbook_directories():
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.md")):
                try:
                    workflow = load_workflow(path)
                except (OSError, yaml.YAMLError, ValueError):
                    continue
                if workflow is not None:
                    self._workflows[workflow.name] = workflow

    def all(self) -> list[WorkflowSpec]:
        return sorted(self._workflows.values(), key=lambda item: item.name)

    def get(self, name: str) -> WorkflowSpec | None:
        return self._workflows.get(name)


class CoreWorkflowPlanner:
    def __init__(self, registry: WorkflowRegistry) -> None:
        self.registry = registry

    def select(
        self, intent: CoreIntent, reviewed: tuple[ReviewedWorkflow, ...]
    ) -> CoreWorkflowSelection:
        intent = CoreIntent.model_validate(intent.model_dump())
        if len(reviewed) > 64:
            raise ValueError("reviewed workflows must be unique and bounded to 64")
        pins = tuple(
            ReviewedWorkflow.model_validate(pin.model_dump()) for pin in reviewed
        )
        if len({pin.name for pin in pins}) != len(pins):
            raise ValueError("reviewed workflows must be unique and bounded to 64")

        def unresolved(reason: str, outcome: str = "blocked") -> CoreWorkflowSelection:
            return CoreWorkflowSelection(
                intent_fingerprint=intent.fingerprint(),
                outcome=outcome,
                public_reason=reason,
            )

        if intent.workflow_name:
            pins = tuple(pin for pin in pins if pin.name == intent.workflow_name)
            if not pins:
                return unresolved("requested workflow is not reviewed")
        candidates: list[WorkflowSpec] = []
        for pin in pins:
            current = self.registry.get(pin.name)
            if current is None:
                return unresolved("reviewed workflow is missing or changed")
            spec = WorkflowSpec.model_validate(current.model_dump())
            if spec.version != pin.version or spec.fingerprint() != pin.fingerprint:
                return unresolved("reviewed workflow is missing or changed")
            if spec.mode != intent.mode:
                if intent.workflow_name:
                    return unresolved("requested workflow mode does not match intent")
                continue
            candidates.append(spec)
        if not candidates:
            return unresolved(
                "no reviewed workflow matches the requested mode", "needs_input"
            )
        if len(candidates) > 1:
            return unresolved(
                "multiple reviewed workflows match; choose one explicitly",
                "needs_input",
            )
        chosen = candidates[0]
        return CoreWorkflowSelection(
            intent_fingerprint=intent.fingerprint(),
            outcome="selected",
            public_reason=(
                "explicit reviewed workflow selected"
                if intent.workflow_name
                else "only compatible reviewed workflow selected"
            ),
            workflow=ReviewedWorkflow(
                name=chosen.name,
                version=chosen.version,
                fingerprint=chosen.fingerprint(),
            ),
            criteria={
                stage.id: stage.gate.model_copy(deep=True) for stage in chosen.stages
            },
        )

    def decide(self, state: TaskState, spec: WorkflowSpec) -> CoreStageDecision:
        selection = CoreWorkflowSelection.model_validate(
            state.environment.get("core_selection")
        )
        if (
            selection.workflow is None
            or selection.workflow.fingerprint != spec.fingerprint()
        ):
            raise ValueError("Core delegation requires the selected reviewed workflow")
        if "core_strategy" in state.environment and CoreStrategy.model_validate(
            state.environment["core_strategy"]
        ) != CoreStrategy.from_spec(spec):
            raise ValueError("Core strategy no longer matches the reviewed workflow")
        common = {
            "session_id": state.session_id,
            "state_version": state.revision,
            "state_fingerprint": core_state_fingerprint(state),
            "workflow_fingerprint": spec.fingerprint(),
        }

        def stop(outcome: str, reason: str) -> CoreStageDecision:
            request = None
            if outcome in {"needs_review", "failed", "budget_exhausted"}:
                request = self._review_request(state, spec, outcome, reason)
            return CoreStageDecision(
                **common, outcome=outcome, public_reason=reason, review_request=request
            )

        nodes = state.plan.topological_order()
        if "core_stop" in state.environment:
            stop_record = CoreMissionStop.model_validate(state.environment["core_stop"])
            if stop_record.decision.session_id != state.session_id:
                raise ValueError("Core stop requires matching mission provenance")
            return stop("stopped", stop_record.public_reason)
        if state.status is TaskStatus.FAILED or any(
            node.status == "error" for node in nodes
        ):
            return stop(
                "failed", "workflow failure requires review; no automatic replay"
            )
        if state.environment.get("core_dispatch_pending") or any(
            node.status == "running"
            or (
                node.status == "needs_review"
                and spec.stage(node.id).execution is not StageExecution.HUMAN
            )
            for node in nodes
        ):
            return stop(
                "needs_review",
                "interrupted or review-paused work requires human review",
            )
        for node in nodes:
            if (
                node.status != "success"
                or spec.stage(node.id).execution is StageExecution.HUMAN
            ):
                continue
            active = state.active_nodes.get(node.id)
            if (
                active is None
                or active.session_id != state.session_id
                or active.node_id != node.id
                or active.workflow_fingerprint != spec.fingerprint()
                or active.node_fingerprint != node.material_fingerprint()
                or active.outcome is not ActiveOutcome.COMPLETED
                or not active.gate_passed
            ):
                return stop(
                    "needs_review", "completed work lacks bound Active verification"
                )
        if state.unresolved_questions:
            return stop(
                "needs_review", "task has unresolved questions or no ready work"
            )
        if nodes and all(node.status == "success" for node in nodes):
            if state.completion_conditions:
                return stop(
                    "needs_review", "task has unresolved questions or no ready work"
                )
            return stop("complete", "all workflow stages have bound completion")
        ready = [
            node
            for node in nodes
            if node.status in {"pending", "needs_review"}
            and all(
                state.plan.nodes[item].status == "success" for item in node.depends_on
            )
        ]
        stage_order = {stage.id: index for index, stage in enumerate(spec.stages)}
        ready.sort(
            key=lambda node: (node.status != "needs_review", stage_order[node.id])
        )
        if not ready or state.status is TaskStatus.COMPLETE:
            return stop(
                "needs_review", "task has unresolved questions or no ready work"
            )
        node = ready[0]
        stage = spec.stage(node.id)
        human = stage.execution is StageExecution.HUMAN
        if not human and "core_budget" in state.environment:
            budget = CoreBudgetState.model_validate(state.environment["core_budget"])
            reason = budget.stop_reason(stage.max_steps)
            if reason:
                return stop("budget_exhausted", reason)
        if state.status is TaskStatus.BLOCKED and not human:
            return stop(
                "needs_review", "task has unresolved questions or no ready work"
            )
        return CoreStageDecision(
            **common,
            outcome="await_approval" if human else "delegate",
            public_reason=(
                "human workflow gate requires explicit approval"
                if human
                else "one ready stage delegated within its existing bounds"
            ),
            stage_id=node.id,
            node_fingerprint=node.material_fingerprint(),
            max_steps=0 if human else stage.max_steps,
        )

    @staticmethod
    def _review_request(
        state: TaskState, spec: WorkflowSpec, outcome: str, reason: str
    ) -> CoreReviewRequest:
        for stage in spec.stages:
            node = state.plan.nodes[stage.id]
            relevant = (
                node.status == "error"
                if outcome == "failed"
                else node.status in {"running", "needs_review"}
                or node.id == state.environment.get("core_dispatch_pending")
                or (
                    node.status == "success"
                    and reason == "completed work lacks bound Active verification"
                )
            )
            if not relevant or stage.execution is StageExecution.HUMAN:
                continue
            active = state.active_nodes.get(node.id)
            if (
                active is not None
                and active.session_id == state.session_id
                and active.node_id == node.id
                and active.workflow_fingerprint == spec.fingerprint()
                and active.node_fingerprint == node.material_fingerprint()
                and active.outcome is not ActiveOutcome.COMPLETED
                and active.escalation is not None
            ):
                material = (
                    active.outcome is ActiveOutcome.NEEDS_REPLAN
                    or active.escalation.kind is ActiveEscalationKind.MATERIAL_CHANGE
                )
                encoded = json.dumps(
                    active.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                return CoreReviewRequest(
                    category="material_replan" if material else "escalation",
                    public_reason=(
                        "material replanning requires separate human review; no changes applied"
                        if material
                        else "Active escalation requires human review; no automatic retry"
                    ),
                    stage_id=node.id,
                    node_fingerprint=node.material_fingerprint(),
                    active_fingerprint=hashlib.sha256(
                        encoded.encode("utf-8")
                    ).hexdigest(),
                    active_outcome=active.outcome,
                    escalation_kind=active.escalation.kind,
                )
            return CoreReviewRequest(
                category="review",
                public_reason="mission stop requires human review; no authority granted",
                stage_id=node.id,
                node_fingerprint=node.material_fingerprint(),
            )
        return CoreReviewRequest(
            category="review",
            public_reason="mission stop requires human review; no authority granted",
        )
