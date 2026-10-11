"""Declarative workflow contracts.

Workflows own ordering, gates, and durable progress. They deliberately do not
own commands: a stage executor may use the universal agent, but every concrete
action still crosses the existing governed execution seam.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..planner import CompletionCriterion, PlanGraph, PlanNode, RetryCategory
from ..schema import (
    ActiveEscalationKind,
    ActiveNodeResult,
    ActiveObservation,
    TaskMode,
    TaskState,
)
from ..schema import (
    ActiveOutcome as StageOutcome,
)
from ..skills.base import RiskLevel

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def file_path_fingerprint(path: str) -> str:
    canonical = os.path.normcase(str(Path(path).resolve(strict=False)))
    return hashlib.sha256(os.fsencode(canonical)).hexdigest()


class StageExecution(str, Enum):
    AGENT = "agent"
    HUMAN = "human"


class ReadStageAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_name: str = Field(min_length=1, max_length=64)
    workflow_version: str = Field(min_length=1, max_length=64)
    stage_id: str = Field(min_length=1, max_length=64)
    capability: str
    params: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=1, ge=1, le=2)

    @field_validator("capability")
    @classmethod
    def read_capability_only(cls, value: str) -> str:
        if value not in {
            "file_read",
            "file_list",
            "file_search",
            "process_list",
            "service_status",
            "list_tools",
        }:
            raise ValueError(
                "model-free stage action must be a supported READ capability"
            )
        return value

    @model_validator(mode="after")
    def bound_parameters(self) -> ReadStageAction:
        try:
            encoded = json.dumps(self.params, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("read action parameters must be JSON values") from exc
        if len(encoded) > 8192:
            raise ValueError("read action parameters exceed the 8192-character limit")
        return self


class WorkflowGate(BaseModel):
    """Deterministic requirements checked after a stage executor returns."""

    require_final: bool = True
    min_successful_actions: int = Field(default=0, ge=0, le=100)
    require_evidence: bool = False
    expected_file_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    expected_file_path: str = Field(default="", max_length=4096)
    expected_file_size_bytes: int | None = Field(
        default=None, ge=0, le=2**63 - 1, strict=True
    )

    @field_validator("expected_file_path")
    @classmethod
    def absolute_file_path(cls, value: str) -> str:
        if not value:
            return value
        if "\x00" in value or not Path(value).is_absolute():
            raise ValueError("expected file path must be absolute")
        try:
            return str(Path(value).resolve(strict=False))
        except (OSError, RuntimeError) as exc:
            raise ValueError("expected file path cannot be resolved") from exc

    @model_validator(mode="after")
    def file_path_needs_digest(self) -> WorkflowGate:
        if self.expected_file_path and not self.expected_file_sha256:
            raise ValueError("expected file path requires an exact file SHA-256")
        return self

    def completion_conditions(self) -> list[CompletionCriterion]:
        conditions: list[CompletionCriterion] = []
        if self.min_successful_actions:
            conditions.append(
                CompletionCriterion(
                    kind="at_least",
                    field="successful_actions",
                    expected=self.min_successful_actions,
                )
            )
        if self.require_evidence:
            conditions.append(
                CompletionCriterion(kind="at_least", field="evidence_count", expected=1)
            )
        return conditions

    def check(
        self,
        result: StageResult,
        observations: Sequence[ActiveObservation] | None = None,
    ) -> tuple[bool, list[str]]:
        failures: list[str] = []
        trusted = (
            observations
            if observations is not None
            else (result.active.observations if result.active is not None else None)
        )
        if not result.success:
            failures.append(result.error or "stage executor reported failure")
        if self.require_final and not result.final.strip():
            failures.append("stage did not produce a final result")
        if result.successful_actions < self.min_successful_actions:
            failures.append(
                "stage requires at least "
                f"{self.min_successful_actions} successful governed action(s)"
            )
        protected = (
            any(
                item.success and item.evidence_id and item.evidence_hash
                for item in trusted
            )
            if trusted is not None
            else any(link.id and link.sha256 for link in result.evidence)
        )
        if self.require_evidence and not protected:
            failures.append("stage produced no protected evidence reference")
        file_reads = [
            item
            for item in trusted or ()
            if item.success
            and item.capability == "file_read"
            and item.evidence_id
            and item.evidence_hash
        ]
        expected_path_hash = (
            file_path_fingerprint(self.expected_file_path)
            if self.expected_file_path
            else ""
        )
        if expected_path_hash and not any(
            item.signals.get("file_path_sha256") == expected_path_hash
            for item in file_reads
        ):
            failures.append("governed file path does not match the expected artifact")
        if self.expected_file_sha256 and not any(
            item.signals.get("file_sha256") == self.expected_file_sha256
            for item in file_reads
        ):
            failures.append("governed file digest does not match the expected SHA-256")
        if self.expected_file_size_bytes is not None and not any(
            item.signals.get("file_size_bytes") == str(self.expected_file_size_bytes)
            for item in file_reads
        ):
            failures.append("governed file size does not match the expected bytes")
        if (
            self.expected_file_sha256
            and self.expected_file_size_bytes is not None
            and not any(
                item.signals.get("file_sha256") == self.expected_file_sha256
                and item.signals.get("file_size_bytes")
                == str(self.expected_file_size_bytes)
                for item in file_reads
            )
        ):
            failures.append("governed file digest and size were not observed together")
        if expected_path_hash and not any(
            item.signals.get("file_path_sha256") == expected_path_hash
            and item.signals.get("file_sha256") == self.expected_file_sha256
            and (
                self.expected_file_size_bytes is None
                or item.signals.get("file_size_bytes")
                == str(self.expected_file_size_bytes)
            )
            for item in file_reads
        ):
            failures.append(
                "governed file artifact criteria were not observed together"
            )
        return not failures, failures


class WorkflowStage(BaseModel):
    id: str
    title: str
    objective: str
    depends_on: list[str] = Field(default_factory=list)
    execution: StageExecution = StageExecution.AGENT
    model_role: str = "worker"
    risk: RiskLevel = RiskLevel.READ
    max_steps: int = Field(default=8, ge=1, le=32)
    instructions: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    gate: WorkflowGate = Field(default_factory=WorkflowGate)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("stage id must be a lowercase identifier")
        return value

    @field_validator("model_role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"planner", "worker", "reviewer", "coder"}:
            raise ValueError("unsupported workflow model role")
        return value


class WorkflowSpec(BaseModel):
    name: str
    description: str
    version: str = "1"
    mode: TaskMode = TaskMode.HYBRID
    target_required: bool = False
    stages: list[WorkflowStage] = Field(min_length=1)
    guidance: str = ""
    source: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("workflow name must be a lowercase identifier")
        return value

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowSpec:
        ids = [stage.id for stage in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("workflow stage ids must be unique")
        known = set(ids)
        for stage in self.stages:
            missing = set(stage.depends_on) - known
            if missing:
                raise ValueError(
                    f"stage '{stage.id}' depends on unknown stages: "
                    + ", ".join(sorted(missing))
                )
        self.to_plan("validation").validate_edges()
        return self

    def to_plan(self, goal: str) -> PlanGraph:
        graph = PlanGraph(goal=goal, reasoning=f"workflow:{self.name}@{self.version}")
        for stage in self.stages:
            graph.add_node(
                PlanNode(
                    id=stage.id,
                    capability="workflow_stage",
                    description=stage.title,
                    params={
                        "workflow": self.name,
                        "workflow_version": self.version,
                        "objective": stage.objective,
                        "execution": stage.execution.value,
                        "model_role": stage.model_role,
                        "risk": stage.risk.value,
                        "max_steps": stage.max_steps,
                        "instructions": stage.instructions,
                        "deliverables": stage.deliverables,
                        "gate": stage.gate.model_dump(mode="json"),
                    },
                    depends_on=stage.depends_on,
                    retry_category=RetryCategory.MANUAL_REVIEW,
                    max_attempts=1,
                    idempotency_key=f"{self.name}-{self.version}-{stage.id}",
                )
            )
        return graph

    def fingerprint(self) -> str:
        payload = self.model_dump(exclude={"source"}, mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def stage(self, stage_id: str) -> WorkflowStage:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        raise KeyError(stage_id)


class CoreIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective: str = Field(min_length=1, max_length=4096)
    mode: TaskMode
    workflow_name: str = Field(default="", max_length=64)

    @field_validator("objective")
    @classmethod
    def nonempty_objective(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Core objective must be nonempty text")
        return value.strip()

    @field_validator("workflow_name")
    @classmethod
    def workflow_identifier(cls, value: str) -> str:
        if value and not _IDENTIFIER.fullmatch(value):
            raise ValueError("Core workflow name must be a lowercase identifier")
        return value

    def fingerprint(self) -> str:
        from ..runtime.coordinator import redact_sensitive

        payload = {
            "objective": redact_sensitive(self.objective),
            "mode": self.mode.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ReviewedWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    version: str = Field(min_length=1, max_length=64)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class CoreWorkflowSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    intent_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["selected", "needs_input", "blocked"]
    public_reason: Literal[
        "explicit reviewed workflow selected",
        "only compatible reviewed workflow selected",
        "multiple reviewed workflows match; choose one explicitly",
        "no reviewed workflow matches the requested mode",
        "requested workflow is not reviewed",
        "reviewed workflow is missing or changed",
        "requested workflow mode does not match intent",
    ]
    workflow: ReviewedWorkflow | None = None
    criteria: dict[str, WorkflowGate] = Field(default_factory=dict)

    @model_validator(mode="after")
    def selected_workflow_required(self) -> CoreWorkflowSelection:
        selected_reasons = {
            "explicit reviewed workflow selected",
            "only compatible reviewed workflow selected",
        }
        if self.outcome == "selected":
            if (
                self.workflow is None
                or not self.criteria
                or self.public_reason not in selected_reasons
            ):
                raise ValueError(
                    "Core selection requires reviewed workflow and criteria"
                )
        elif (
            self.workflow is not None
            or self.criteria
            or self.public_reason in selected_reasons
        ):
            raise ValueError("unresolved Core selection cannot contain a workflow plan")
        needs_input = self.public_reason in {
            "multiple reviewed workflows match; choose one explicitly",
            "no reviewed workflow matches the requested mode",
        }
        if (self.outcome == "needs_input") != needs_input:
            raise ValueError("Core outcome must match its public reason")
        return self


class CoreStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    policy: Literal["reviewed-declaration-order-v1"] = "reviewed-declaration-order-v1"
    workflow: ReviewedWorkflow
    stage_order: tuple[str, ...] = Field(min_length=1, max_length=64)
    delegation: Literal["one bounded stage per fresh decision"] = (
        "one bounded stage per fresh decision"
    )
    recovery: Literal["human-reviewed replacement; no automatic replay"] = (
        "human-reviewed replacement; no automatic replay"
    )

    @classmethod
    def from_spec(cls, spec: WorkflowSpec) -> CoreStrategy:
        return cls(
            workflow=ReviewedWorkflow(
                name=spec.name, version=spec.version, fingerprint=spec.fingerprint()
            ),
            stage_order=tuple(stage.id for stage in spec.stages),
        )


def core_state_fingerprint(state: TaskState) -> str:
    payload = state.model_dump(mode="json", exclude={"created_at", "updated_at"})
    payload["environment"].pop("core_decision", None)
    payload["environment"].pop("core_decision_consumed", None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CoreMissionBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_stage_dispatches: int = Field(ge=0, le=1024, strict=True)
    max_reserved_steps: int = Field(ge=0, le=32768, strict=True)


class CoreBudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    limits: CoreMissionBudget
    stage_dispatches: int = Field(default=0, ge=0, le=1024, strict=True)
    reserved_steps: int = Field(default=0, ge=0, le=32768, strict=True)

    @model_validator(mode="after")
    def usage_within_limits(self) -> CoreBudgetState:
        if (
            self.stage_dispatches > self.limits.max_stage_dispatches
            or self.reserved_steps > self.limits.max_reserved_steps
            or (self.stage_dispatches == 0) != (self.reserved_steps == 0)
            or self.reserved_steps < self.stage_dispatches
            or self.reserved_steps > self.stage_dispatches * 32
        ):
            raise ValueError("Core budget usage must be consistent and within limits")
        return self

    def stop_reason(self, steps: int) -> str:
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or not 1 <= steps <= 32
        ):
            raise ValueError("Core reservation requires an existing bounded stage")
        if self.stage_dispatches >= self.limits.max_stage_dispatches:
            return "mission stage-dispatch budget exhausted"
        if self.reserved_steps + steps > self.limits.max_reserved_steps:
            return "mission step-reservation budget cannot cover the next stage"
        return ""

    def reserve(self, steps: int) -> CoreBudgetState:
        if self.stop_reason(steps):
            raise ValueError("Core mission budget cannot reserve the delegated stage")
        return CoreBudgetState(
            limits=self.limits,
            stage_dispatches=self.stage_dispatches + 1,
            reserved_steps=self.reserved_steps + steps,
        )


class CoreReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["material_replan", "escalation", "review"]
    public_reason: Literal[
        "material replanning requires separate human review; no changes applied",
        "Active escalation requires human review; no automatic retry",
        "mission stop requires human review; no authority granted",
    ]
    stage_id: str = Field(default="", pattern=r"^(?:[a-z][a-z0-9_-]{0,63})?$")
    node_fingerprint: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    active_fingerprint: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    active_outcome: StageOutcome | None = None
    escalation_kind: ActiveEscalationKind | None = None

    @model_validator(mode="after")
    def bound_source(self) -> CoreReviewRequest:
        reasons = {
            "material_replan": "material replanning requires separate human review; no changes applied",
            "escalation": "Active escalation requires human review; no automatic retry",
            "review": "mission stop requires human review; no authority granted",
        }
        if self.public_reason != reasons[self.category]:
            raise ValueError("Core review category and public reason disagree")
        if bool(self.stage_id) != bool(self.node_fingerprint):
            raise ValueError("Core review node reference must be paired")
        sourced = self.category != "review"
        if sourced != bool(self.active_fingerprint) or sourced != (
            self.active_outcome is not None and self.escalation_kind is not None
        ):
            raise ValueError(
                "Core escalation requires a bound incomplete Active source"
            )
        if not sourced and (
            self.active_outcome is not None or self.escalation_kind is not None
        ):
            raise ValueError("unclassified Core review cannot claim an Active cause")
        if sourced:
            if not self.stage_id or self.active_outcome is StageOutcome.COMPLETED:
                raise ValueError("Core escalation requires an incomplete bound node")
            material = (
                self.active_outcome is StageOutcome.NEEDS_REPLAN
                or self.escalation_kind is ActiveEscalationKind.MATERIAL_CHANGE
            )
            if (self.category == "material_replan") != material:
                raise ValueError("Core material replan must match its Active cause")
        return self


class CoreStageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    session_id: str = Field(min_length=1, max_length=128)
    state_version: int = Field(ge=0, strict=True)
    state_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    workflow_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal[
        "delegate",
        "await_approval",
        "needs_review",
        "complete",
        "failed",
        "budget_exhausted",
        "stopped",
    ]
    public_reason: Literal[
        "one ready stage delegated within its existing bounds",
        "human workflow gate requires explicit approval",
        "interrupted or review-paused work requires human review",
        "completed work lacks bound Active verification",
        "task has unresolved questions or no ready work",
        "all workflow stages have bound completion",
        "workflow failure requires review; no automatic replay",
        "mission stage-dispatch budget exhausted",
        "mission step-reservation budget cannot cover the next stage",
        "mission explicitly stopped by human; no automatic resume",
    ]
    stage_id: str = Field(default="", pattern=r"^(?:[a-z][a-z0-9_-]{0,63})?$")
    node_fingerprint: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    max_steps: int = Field(default=0, ge=0, le=32, strict=True)
    review_request: CoreReviewRequest | None = None

    @model_validator(mode="after")
    def bound_decision(self) -> CoreStageDecision:
        reasons = {
            "delegate": {"one ready stage delegated within its existing bounds"},
            "await_approval": {"human workflow gate requires explicit approval"},
            "needs_review": {
                "interrupted or review-paused work requires human review",
                "completed work lacks bound Active verification",
                "task has unresolved questions or no ready work",
            },
            "complete": {"all workflow stages have bound completion"},
            "failed": {"workflow failure requires review; no automatic replay"},
            "budget_exhausted": {
                "mission stage-dispatch budget exhausted",
                "mission step-reservation budget cannot cover the next stage",
            },
            "stopped": {"mission explicitly stopped by human; no automatic resume"},
        }
        if self.public_reason not in reasons[self.outcome]:
            raise ValueError("Core decision outcome and public reason disagree")
        if self.outcome in {"delegate", "await_approval"}:
            if not self.stage_id or not self.node_fingerprint:
                raise ValueError("Core stage decision requires a bound node")
        elif self.stage_id or self.node_fingerprint:
            raise ValueError("Core terminal or review decision cannot delegate a node")
        if (self.outcome == "delegate") != (self.max_steps > 0):
            raise ValueError("only Core delegation may allocate existing stage steps")
        if self.review_request is not None and self.outcome not in {
            "needs_review",
            "failed",
            "budget_exhausted",
        }:
            raise ValueError("only a Core review stop may carry a review request")
        return self

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CoreReviewResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    decision: CoreStageDecision
    disposition: Literal["acknowledged", "rejected"]

    @model_validator(mode="after")
    def review_required(self) -> CoreReviewResolution:
        if self.decision.review_request is None:
            raise ValueError("Core review resolution requires a review request")
        return self


class CoreMissionStop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    decision: CoreStageDecision
    public_reason: Literal[
        "mission explicitly stopped by human; no automatic resume"
    ] = "mission explicitly stopped by human; no automatic resume"


class CoreReplanTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    decision: CoreStageDecision
    replacement: CoreWorkflowSelection
    replacement_session_id: str = Field(default="", max_length=128)
    public_reason: Literal[
        "human reviewed replacement; prior run stopped; no authority expanded"
    ] = "human reviewed replacement; prior run stopped; no authority expanded"

    @model_validator(mode="after")
    def reviewed_replacement_required(self) -> CoreReplanTransition:
        if (
            self.decision.review_request is None
            or self.replacement.outcome != "selected"
        ):
            raise ValueError(
                "Core replanning requires a review stop and reviewed replacement"
            )
        return self


class CoreReplanOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_session_id: str = Field(min_length=1, max_length=128)
    decision_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceLink(BaseModel):
    id: str
    sha256: str = ""
    summary: str = ""


class StageResult(BaseModel):
    success: bool
    outcome: StageOutcome | None = None
    final: str = ""
    summary: str = ""
    successful_actions: int = Field(default=0, ge=0)
    evidence: list[EvidenceLink] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    failed_criteria: list[str] = Field(default_factory=list)
    active: ActiveNodeResult | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> StageResult:
        if self.outcome is None:
            self.outcome = (
                StageOutcome.COMPLETED if self.success else StageOutcome.FAILED
            )
        if self.success != (self.outcome is StageOutcome.COMPLETED):
            raise ValueError("stage success and outcome disagree")
        if self.active is not None:
            if self.active.outcome is not self.outcome:
                raise ValueError("active node and stage outcomes disagree")
            if self.successful_actions != sum(
                item.success for item in self.active.observations
            ):
                raise ValueError("stage action count differs from active observations")
            protected = {
                (item.evidence_id, item.evidence_hash)
                for item in self.active.observations
                if item.evidence_id and item.evidence_hash
            }
            if any((link.id, link.sha256) not in protected for link in self.evidence):
                raise ValueError(
                    "stage evidence is not linked to an active observation"
                )
        return self


class WorkflowStageContext(BaseModel):
    session_id: str
    workflow_name: str
    workflow_version: str
    goal: str
    target: str = ""
    stage: WorkflowStage
    guidance: str = ""
    prior_results: list[dict[str, Any]] = Field(default_factory=list)


class PriorEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_id: str = Field(min_length=1, max_length=64)
    evidence_id: str = Field(min_length=1, max_length=128)
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class BoundStageContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    workflow_name: str
    workflow_version: str
    stage_id: str
    goal: str
    target: str
    workflow_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    node_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    prior_results: tuple[dict[str, Any], ...] = ()
    prior_evidence: tuple[PriorEvidenceRef, ...] = Field(default=(), max_length=8)

    @classmethod
    def from_task(cls, state: Any, context: WorkflowStageContext) -> BoundStageContext:
        from ..runtime.coordinator import redact_sensitive

        node = state.plan.nodes.get(context.stage.id)
        expected = {
            "workflow": context.workflow_name,
            "workflow_version": context.workflow_version,
            "objective": context.stage.objective,
            "execution": context.stage.execution.value,
            "model_role": context.stage.model_role,
            "risk": context.stage.risk.value,
            "max_steps": context.stage.max_steps,
            "instructions": context.stage.instructions,
            "deliverables": context.stage.deliverables,
            "gate": context.stage.gate.model_dump(mode="json"),
        }
        if (
            context.session_id != state.session_id
            or context.goal != state.objective
            or context.workflow_name != state.environment.get("workflow")
            or context.workflow_version != state.environment.get("workflow_version")
            or context.target != str(state.environment.get("target", ""))
            or node is None
            or node.capability != "workflow_stage"
            or node.status not in {"pending", "running"}
            or node.description != context.stage.title
            or node.params != expected
            or node.depends_on != context.stage.depends_on
            or any(
                state.plan.nodes.get(dependency) is None
                or state.plan.nodes[dependency].status != "success"
                for dependency in node.depends_on
            )
        ):
            raise ValueError("stage context does not match the durable task plan")
        prior = tuple(
            {
                "stage": str(item.get("stage", ""))[:64],
                "success": item.get("success") is True,
                "summary": redact_sensitive(str(item.get("summary", "")))[:400],
                "final": redact_sensitive(str(item.get("final", "")))[:1000],
            }
            for item in context.prior_results[-8:]
        )
        prior_evidence: list[PriorEvidenceRef] = []
        for dependency_id in node.depends_on:
            dependency = state.plan.nodes[dependency_id]
            active = state.active_nodes.get(dependency_id)
            if (
                dependency.status != "success"
                or active is None
                or active.session_id != state.session_id
                or active.node_id != dependency_id
                or active.workflow_fingerprint
                != state.environment.get("workflow_fingerprint")
                or active.node_fingerprint != dependency.material_fingerprint()
                or active.outcome is not StageOutcome.COMPLETED
                or not active.gate_passed
            ):
                continue
            for observation in active.observations:
                if (
                    observation.success
                    and observation.evidence_id
                    and observation.evidence_hash
                ):
                    prior_evidence.append(
                        PriorEvidenceRef(
                            stage_id=dependency_id,
                            evidence_id=observation.evidence_id,
                            evidence_hash=observation.evidence_hash,
                        )
                    )
                    if len(prior_evidence) == 8:
                        break
            if len(prior_evidence) == 8:
                break
        return cls(
            session_id=context.session_id,
            workflow_name=context.workflow_name,
            workflow_version=context.workflow_version,
            stage_id=context.stage.id,
            goal=context.goal,
            target=context.target,
            workflow_fingerprint=str(state.environment.get("workflow_fingerprint", "")),
            node_fingerprint=node.material_fingerprint(),
            prior_results=prior,
            prior_evidence=tuple(prior_evidence),
        )


class WorkflowRunReport(BaseModel):
    session_id: str
    workflow: str
    workflow_version: str
    status: str
    goal: str
    target: str = ""
    ready: list[str] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)
    message: str = ""
