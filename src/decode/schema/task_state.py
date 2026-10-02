"""The live task-state object (Neural Schema, subsystem 04).

Structured world-state shared between the model and the runtime. The agent loop
renders a *compact* view of it into the prompt each turn and updates it after
every observation, so reasoning does not rely solely on a growing chat log.

The plan/action DAG is a reused :class:`PlanGraph`; completion conditions reuse
:class:`CompletionCriterion` — this module adds no new planning machinery.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..planner.dag import CompletionCriterion, PlanGraph


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _uuid() -> str:
    return str(uuid4())


class TaskMode(str, Enum):
    CODING = "coding"
    SECURITY = "security"
    HYBRID = "hybrid"


class TaskStatus(str, Enum):
    INVESTIGATING = "investigating"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    FAILED = "failed"


class ActiveOutcome(str, Enum):
    COMPLETED = "completed"
    NEEDS_REPLAN = "needs_replan"
    BLOCKED = "blocked"
    FAILED = "failed"


class ActiveEscalationKind(str, Enum):
    POLICY = "policy"
    APPROVAL = "approval"
    DEPENDENCY = "dependency"
    VERIFICATION = "verification"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    SAFETY = "safety"
    EXECUTION = "execution"
    BUDGET = "budget"
    MATERIAL_CHANGE = "material_change"
    LEGACY_UNCLASSIFIED = "legacy_unclassified"


class ActiveEscalation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ActiveEscalationKind
    request_id: str = ""


class ActiveObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    capability: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=128)
    status: Literal["success", "denied", "blocked", "error", "timeout", "cancelled"]
    success: bool = False
    error_category: Literal[
        "",
        "policy_denial",
        "approval_required",
        "approval_rejected",
        "approval_invalid",
        "approval_expired",
        "missing_dependency",
        "timeout",
        "cancellation",
        "execution_failure",
        "telemetry_failure",
        "unsupported_action",
    ] = ""
    evidence_id: str = Field(default="", max_length=128)
    evidence_hash: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    signals: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def evidence_pair_and_success(self) -> ActiveObservation:
        if bool(self.evidence_id) != bool(self.evidence_hash):
            raise ValueError("active observation evidence id and hash must be paired")
        if self.success and self.status != "success":
            raise ValueError("active observation success requires execution success")
        if any(
            not (
                (name == "file_sha256" and re.fullmatch(r"[a-f0-9]{64}", value))
                or (name == "file_path_sha256" and re.fullmatch(r"[a-f0-9]{64}", value))
                or (
                    name == "file_size_bytes"
                    and re.fullmatch(r"0|[1-9][0-9]*", value)
                    and len(value) <= 19
                    and int(value) <= 2**63 - 1
                )
            )
            for name, value in self.signals.items()
        ):
            raise ValueError("active observation signals must be known file metadata")
        return self


class ActiveNodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    workflow_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    node_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: ActiveOutcome
    gate_passed: bool = False
    attempts: int = Field(default=0, ge=0, le=32)
    observations: tuple[ActiveObservation, ...] = Field(default=(), max_length=32)
    failed_criteria: tuple[str, ...] = ()
    escalation: ActiveEscalation | None = None

    @model_validator(mode="after")
    def completion_requires_observation_and_gate(self) -> ActiveNodeResult:
        if self.outcome is ActiveOutcome.COMPLETED and (
            not self.gate_passed
            or not any(
                observation.success
                and observation.evidence_id
                and observation.evidence_hash
                for observation in self.observations
            )
            or self.failed_criteria
            or self.escalation is not None
        ):
            raise ValueError(
                "active completion requires a successful gated protected observation"
            )
        if self.outcome is not ActiveOutcome.COMPLETED and self.escalation is None:
            raise ValueError("incomplete active result requires typed escalation")
        if (
            self.escalation is not None
            and self.escalation.request_id
            and not any(
                item.request_id == self.escalation.request_id
                for item in self.observations
            )
        ):
            raise ValueError("active escalation must refer to an observed request")
        if self.attempts < sum(
            observation.status != "blocked" for observation in self.observations
        ):
            raise ValueError("active attempts cannot be below observed executions")
        return self


class Hypothesis(BaseModel):
    id: str = Field(default_factory=_uuid)
    statement: str
    status: str = "open"  # open | supported | refuted
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ActionRecord(BaseModel):
    step: int
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    thought: str = ""
    ts: str = Field(default_factory=_now)


class Observation(BaseModel):
    step: int
    tool: str
    success: bool = False
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    evidence_ref: str = ""
    evidence_hash: str = ""
    ts: str = Field(default_factory=_now)


class Artifact(BaseModel):
    """A significant operation's durable record, linked to protected evidence."""

    id: str = Field(default_factory=_uuid)
    source: str = ""
    action: str = ""
    related_step: int = 0
    summary: str = ""
    evidence_id: str = ""
    evidence_hash: str = ""
    confidence: str = "medium"
    ts: str = Field(default_factory=_now)


class Finding(BaseModel):
    id: str = Field(default_factory=_uuid)
    title: str
    detail: str = ""
    severity: str = "info"  # info | low | medium | high | critical
    confidence: str = "medium"
    evidence_ref: str = ""
    related_action: str = ""


class ScopeView(BaseModel):
    """A read-only snapshot of the active governance scope for the prompt."""

    read_roots: list[str] = Field(default_factory=list)
    write_roots: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    allow_destructive: bool = False


class TaskState(BaseModel):
    session_id: str = Field(default_factory=_uuid)
    objective: str = ""
    mode: TaskMode = TaskMode.HYBRID
    scope: ScopeView = Field(default_factory=ScopeView)
    constraints: list[str] = Field(default_factory=list)
    environment: dict[str, Any] = Field(default_factory=dict)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    plan: PlanGraph = Field(default_factory=PlanGraph)
    actions: list[ActionRecord] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    active_nodes: dict[str, ActiveNodeResult] = Field(default_factory=dict)
    unresolved_questions: list[str] = Field(default_factory=list)
    completion_conditions: list[CompletionCriterion] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.INVESTIGATING
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    # ── mutation ────────────────────────────────────────────────────────
    def _touch(self) -> None:
        self.updated_at = _now()

    def record_action(
        self, tool: str, params: dict[str, Any] | None = None, thought: str = ""
    ) -> ActionRecord:
        action = ActionRecord(
            step=len(self.actions) + 1, tool=tool, params=params or {}, thought=thought
        )
        self.actions.append(action)
        self._touch()
        return action

    def record_observation(self, tool: str, observation: dict[str, Any]) -> Observation:
        evidence = observation.get("evidence") or {}
        obs = Observation(
            step=len(self.observations) + 1,
            tool=tool,
            success=bool(observation.get("success")),
            summary=str(observation.get("summary", ""))[:400],
            data=observation.get("data") or {},
            evidence_ref=str(evidence.get("id", "")),
            evidence_hash=str(evidence.get("sha256", "")),
        )
        self.observations.append(obs)
        # Link the immutable evidence captured for this step as a task artifact.
        if obs.evidence_ref:
            self.add_artifact(
                source=tool,
                action=tool,
                related_step=obs.step,
                summary=obs.summary,
                evidence_id=obs.evidence_ref,
                evidence_hash=obs.evidence_hash,
            )
        self._touch()
        return obs

    def add_artifact(
        self,
        *,
        source: str = "",
        action: str = "",
        related_step: int = 0,
        summary: str = "",
        evidence_id: str = "",
        evidence_hash: str = "",
        confidence: str = "medium",
    ) -> Artifact:
        artifact = Artifact(
            source=source,
            action=action,
            related_step=related_step,
            summary=summary,
            evidence_id=evidence_id,
            evidence_hash=evidence_hash,
            confidence=confidence,
        )
        self.artifacts.append(artifact)
        self._touch()
        return artifact

    def add_hypothesis(self, statement: str, confidence: float = 0.0) -> Hypothesis:
        hypothesis = Hypothesis(statement=statement, confidence=confidence)
        self.hypotheses.append(hypothesis)
        self._touch()
        return hypothesis

    def add_finding(self, title: str, **kwargs: Any) -> Finding:
        finding = Finding(title=title, **kwargs)
        self.findings.append(finding)
        self._touch()
        return finding

    def add_question(self, question: str) -> None:
        if question and question not in self.unresolved_questions:
            self.unresolved_questions.append(question)
            self._touch()

    def resolve_question(self, question: str) -> None:
        if question in self.unresolved_questions:
            self.unresolved_questions.remove(question)
            self._touch()

    def mark(self, status: str | TaskStatus) -> None:
        self.status = TaskStatus(status)
        self._touch()

    # ── completion ──────────────────────────────────────────────────────
    def evaluate_completion(self, values: dict[str, Any]) -> tuple[bool, list[str]]:
        """Check the objective-level completion conditions against a result dict.

        Reuses :meth:`CompletionCriterion.check`. Returns ``(complete, failures)``;
        with no conditions declared, the objective is never auto-completed.
        """
        if not self.completion_conditions:
            return False, ["no completion conditions declared"]
        failures: list[str] = []
        for criterion in self.completion_conditions:
            ok, reason = criterion.check(values)
            if not ok:
                failures.append(reason)
        return (not failures), failures

    # ── rendering ───────────────────────────────────────────────────────
    def render_compact(self, max_items: int = 5) -> str:
        """A short, structured view injected into the prompt each turn.

        Deliberately compact (recent items only) so the state stays a world-model,
        not a second chat log.
        """
        lines: list[str] = ["TASK STATE"]
        lines.append(f"Objective: {self.objective or '(unset)'}")
        lines.append(f"Mode: {self.mode.value} | Status: {self.status.value}")
        scope = self.scope
        lines.append(
            "Scope: "
            f"read={scope.read_roots or '-'} write={scope.write_roots or '-'} "
            f"targets={scope.targets or '-'} destructive={'yes' if scope.allow_destructive else 'no'}"
        )
        if self.constraints:
            lines.append("Constraints: " + "; ".join(self.constraints[:max_items]))
        if self.environment:
            env = ", ".join(
                f"{k}={v}" for k, v in list(self.environment.items())[:max_items]
            )
            lines.append(f"Environment: {env}")
        if self.hypotheses:
            lines.append("Hypotheses:")
            for hyp in self.hypotheses[-max_items:]:
                lines.append(f"  - [{hyp.status}] {hyp.statement}")
        if self.actions:
            lines.append("Recent actions:")
            for action in self.actions[-max_items:]:
                obs = next(
                    (o for o in reversed(self.observations) if o.step == action.step),
                    None,
                )
                outcome = "ok" if (obs and obs.success) else ("failed" if obs else "…")
                lines.append(f"  {action.step}. {action.tool} -> {outcome}")
        if self.findings:
            lines.append("Findings:")
            for finding in self.findings[-max_items:]:
                lines.append(f"  - [{finding.severity}] {finding.title}")
        if self.artifacts:
            lines.append(f"Artifacts: {len(self.artifacts)} evidence-linked")
        if self.unresolved_questions:
            lines.append("Open questions:")
            for question in self.unresolved_questions[-max_items:]:
                lines.append(f"  - {question}")
        if self.completion_conditions:
            lines.append(
                f"Completion conditions: {len(self.completion_conditions)} declared"
            )
        return "\n".join(lines)
