"""Declarative workflow contracts.

Workflows own ordering, gates, and durable progress. They deliberately do not
own commands: a stage executor may use the universal agent, but every concrete
action still crosses the existing governed execution seam.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..planner import PlanGraph, PlanNode, RetryCategory
from ..schema import TaskMode
from ..skills.base import RiskLevel

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class StageExecution(str, Enum):
    AGENT = "agent"
    HUMAN = "human"


class WorkflowGate(BaseModel):
    """Deterministic requirements checked after a stage executor returns."""

    require_final: bool = True
    min_successful_actions: int = Field(default=0, ge=0, le=100)
    require_evidence: bool = False

    def check(self, result: StageResult) -> tuple[bool, list[str]]:
        failures: list[str] = []
        if not result.success:
            failures.append(result.error or "stage executor reported failure")
        if self.require_final and not result.final.strip():
            failures.append("stage did not produce a final result")
        if result.successful_actions < self.min_successful_actions:
            failures.append(
                "stage requires at least "
                f"{self.min_successful_actions} successful governed action(s)"
            )
        if self.require_evidence and not result.evidence:
            failures.append("stage produced no protected evidence reference")
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


class EvidenceLink(BaseModel):
    id: str
    sha256: str = ""
    summary: str = ""


class StageResult(BaseModel):
    success: bool
    final: str = ""
    summary: str = ""
    successful_actions: int = Field(default=0, ge=0)
    evidence: list[EvidenceLink] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class WorkflowStageContext(BaseModel):
    session_id: str
    workflow_name: str
    workflow_version: str
    goal: str
    target: str = ""
    stage: WorkflowStage
    guidance: str = ""
    prior_results: list[dict[str, Any]] = Field(default_factory=list)


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
