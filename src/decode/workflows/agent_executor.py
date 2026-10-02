"""Governed universal-agent adapter for deterministic workflow stages."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from typing import Any

from ..app.config import Config
from ..audit import AuditLayer
from ..execution import ExecutionProvider, create_configured_executor
from ..governance import GovernanceGate, ScopePolicy
from ..hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from ..runtime import ExecutionCoordinator, HostController
from ..runtime.coordinator import (
    CoordinatedCancellation,
    CoordinatedResult,
    ExecutionErrorCategory,
    ExecutionRequest,
    ExecutionStatus,
    redact_sensitive,
)
from ..schema import (
    ActiveEscalation,
    ActiveEscalationKind,
    ActiveNodeResult,
    ActiveObservation,
    TaskState,
)
from ..skills.base import RiskLevel
from .models import (
    BoundStageContext,
    EvidenceLink,
    ReadStageAction,
    StageExecution,
    StageOutcome,
    StageResult,
    WorkflowStageContext,
    file_path_fingerprint,
)


def _project_observation(result: CoordinatedResult, provider: str) -> ActiveObservation:
    success = (
        result.status is ExecutionStatus.SUCCESS
        and result.success
        and getattr(result.value, "success", True) is True
    )
    signals: dict[str, str] = {}
    normalized = getattr(result.value, "normalized", None)
    if result.action == "file_read" and success and isinstance(normalized, dict):
        digest = normalized.get("sha256")
        size = normalized.get("size_bytes")
        path = normalized.get("path")
        if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest):
            signals["file_sha256"] = digest
        if type(size) is int and size >= 0:
            signals["file_size_bytes"] = str(size)
        if isinstance(path, str) and path and "\x00" not in path:
            try:
                signals["file_path_sha256"] = file_path_fingerprint(path)
            except (OSError, RuntimeError, ValueError):
                pass
    return ActiveObservation(
        request_id=result.request_id,
        capability=result.action,
        provider=provider,
        status=result.status.value,
        success=success,
        error_category=(
            result.error_category.value if result.error_category is not None else ""
        ),
        evidence_id=result.evidence.id if result.evidence is not None else "",
        evidence_hash=result.evidence.sha256 if result.evidence is not None else "",
        signals=signals,
    )


def _classify_escalation(
    outcome: StageOutcome,
    observations: list[ActiveObservation],
    *,
    override: ActiveEscalationKind | None = None,
) -> ActiveEscalation | None:
    if outcome is StageOutcome.COMPLETED:
        return None
    failed = next((item for item in reversed(observations) if not item.success), None)
    if override is not None:
        return ActiveEscalation(
            kind=override, request_id=failed.request_id if failed else ""
        )
    if failed is not None:
        category = failed.error_category
        if category.startswith("approval_"):
            kind = ActiveEscalationKind.APPROVAL
        elif category == "policy_denial" or failed.status == "denied":
            kind = ActiveEscalationKind.POLICY
        elif category == "missing_dependency":
            kind = ActiveEscalationKind.DEPENDENCY
        elif category == "telemetry_failure":
            kind = ActiveEscalationKind.SAFETY
        elif category == "cancellation" or failed.status == "cancelled":
            kind = ActiveEscalationKind.CANCELLATION
        elif category == "timeout" or failed.status == "timeout":
            kind = ActiveEscalationKind.TIMEOUT
        else:
            kind = ActiveEscalationKind.EXECUTION
        return ActiveEscalation(kind=kind, request_id=failed.request_id)
    return ActiveEscalation(
        kind=(
            ActiveEscalationKind.VERIFICATION
            if outcome is StageOutcome.NEEDS_REPLAN
            else ActiveEscalationKind.BUDGET
            if outcome is StageOutcome.BLOCKED
            else ActiveEscalationKind.EXECUTION
        )
    )


class ActiveStageRuntime:
    """Bound context, working observations, verification, and typed handoff."""

    def __init__(self, state: TaskState, context: WorkflowStageContext) -> None:
        self.bound = BoundStageContext.from_task(state, context)
        self.observations: list[ActiveObservation] = []
        self._state = state
        self._context = context
        self._material = self._envelope()

    def _envelope(self) -> str:
        return json.dumps(
            {
                "session_id": self._state.session_id,
                "objective": self._state.objective,
                "scope": self._state.scope.model_dump(mode="json"),
                "mode": self._state.mode.value,
                "context": self._context.model_dump(mode="json"),
                "node": self._state.plan.nodes[self.bound.stage_id].model_dump(
                    mode="json"
                ),
                "dependencies": {
                    dependency: {
                        "status": self._state.plan.nodes[dependency].status,
                        "fingerprint": self._state.plan.nodes[
                            dependency
                        ].material_fingerprint(),
                        "active": self._state.active_nodes[dependency].model_dump(
                            mode="json"
                        )
                        if dependency in self._state.active_nodes
                        else None,
                    }
                    for dependency in self._context.stage.depends_on
                },
                "environment": self._state.environment,
            },
            sort_keys=True,
            default=str,
        )

    def unchanged(self) -> bool:
        try:
            return self._envelope() == self._material
        except (KeyError, TypeError, ValueError):
            return False

    def record(self, result: CoordinatedResult, provider: str) -> None:
        self.observations.append(_project_observation(result, provider))

    def finish(
        self,
        result: StageResult,
        *,
        attempts: int | None = None,
        escalation: ActiveEscalationKind | None = None,
    ) -> StageResult:
        observations = self.observations
        payload = result.model_dump(mode="python", exclude={"active"})
        payload.update(
            successful_actions=sum(item.success for item in observations),
            evidence=[
                EvidenceLink(id=item.evidence_id, sha256=item.evidence_hash)
                for item in observations
                if item.evidence_id and item.evidence_hash
            ],
            final=redact_sensitive(result.final),
            summary=redact_sensitive(result.summary),
            error=redact_sensitive(result.error),
            data=redact_sensitive(result.data),
            failed_criteria=[redact_sensitive(item) for item in result.failed_criteria],
        )
        result = StageResult.model_validate(payload)
        if not self.unchanged():
            payload.update(
                success=False,
                outcome=StageOutcome.BLOCKED,
                error="active stage envelope changed; review required",
                failed_criteria=[],
            )
            result = StageResult.model_validate(payload)
            escalation = ActiveEscalationKind.MATERIAL_CHANGE
        verified, failures = self._context.stage.gate.check(result, observations)
        if result.success and not any(
            item.success and item.evidence_id and item.evidence_hash
            for item in observations
        ):
            verified = False
            failures.append("active completion requires protected governed evidence")
        if result.success and not verified:
            payload.update(
                success=False,
                outcome=StageOutcome.NEEDS_REPLAN,
                error="stage completion gate unmet",
                failed_criteria=failures,
            )
            result = StageResult.model_validate(payload)
        active = ActiveNodeResult(
            session_id=self.bound.session_id,
            node_id=self.bound.stage_id,
            workflow_fingerprint=self.bound.workflow_fingerprint,
            node_fingerprint=self.bound.node_fingerprint,
            outcome=result.outcome,
            gate_passed=verified,
            attempts=len(observations) if attempts is None else attempts,
            observations=tuple(observations),
            failed_criteria=tuple(result.failed_criteria),
            escalation=_classify_escalation(
                result.outcome, observations, override=escalation
            ),
        )
        return StageResult.model_validate(
            {**result.model_dump(mode="python"), "active": active}
        )


class GovernedAgentStageExecutor:
    """Execute one workflow stage through the existing governed agent loop."""

    def __init__(
        self,
        state: TaskState,
        *,
        provider: str | None = None,
        permission_mode: PermissionMode | str = PermissionMode.ASK,
        approval_callback: Any = None,
    ) -> None:
        self._state = state.model_copy(deep=True)
        self._provider = provider or Config.PROVIDER
        self._permission_mode = PermissionMode(permission_mode)
        self._approval_callback = approval_callback
        self._agent: Any = None
        self._used_stages: set[tuple[str, str]] = set()

    def bind_state(self, state: TaskState) -> None:
        if state.session_id != self._state.session_id:
            raise ValueError("active executor cannot change its session")
        self._state = state.model_copy(deep=True)

    async def __call__(self, context: WorkflowStageContext) -> StageResult:
        try:
            runtime = ActiveStageRuntime(self._state, context)
        except ValueError:
            return StageResult(
                success=False,
                outcome=StageOutcome.BLOCKED,
                error="stage context does not match the durable task plan",
            )
        key = (runtime.bound.session_id, runtime.bound.stage_id)
        if (
            key in self._used_stages
            or context.stage.execution is not StageExecution.AGENT
        ):
            return runtime.finish(
                StageResult(
                    success=False,
                    outcome=StageOutcome.BLOCKED,
                    error="stage is not an unused agent node; review required",
                ),
                escalation=ActiveEscalationKind.POLICY,
            )
        self._used_stages.add(key)
        material_changed = False
        try:
            agent = self._get_agent()
            agent.set_scope(
                self._state.scope.targets,
                allow_destructive=self._state.scope.allow_destructive,
            )
            provider = getattr(agent, "execution_provider", None)
            provider_identity = provider.identify() if provider is not None else None

            def before_call() -> str:
                nonlocal material_changed
                current_provider = getattr(agent, "execution_provider", None)
                material_changed = (
                    not runtime.unchanged()
                    or (
                        current_provider.identify()
                        if current_provider is not None
                        else None
                    )
                    != provider_identity
                    or list(getattr(agent, "_scope_entries", self._state.scope.targets))
                    != self._state.scope.targets
                )
                return (
                    "active stage envelope changed; review required"
                    if material_changed
                    else ""
                )

            result = await agent.run_tool_loop(
                self._prompt(context, runtime.bound),
                filesystem_scope=FilesystemScope(
                    read_roots=self._state.scope.read_roots,
                    write_roots=self._state.scope.write_roots,
                ),
                command_policy=CommandPolicy(),
                permission_mode=self._permission_mode,
                approval_callback=self._approval_callback,
                max_steps=context.stage.max_steps,
                task_mode=self._state.mode,
                model_role=context.stage.model_role,
                completion_conditions=context.stage.gate.completion_conditions(),
                on_governed_result=runtime.record,
                before_governed_call=before_call,
                stop_on_failure=True,
            )
        except asyncio.CancelledError:
            return runtime.finish(
                StageResult(
                    success=False,
                    outcome=StageOutcome.BLOCKED,
                    error="active stage cancelled; review required",
                ),
                escalation=ActiveEscalationKind.CANCELLATION,
            )
        except Exception:
            return runtime.finish(
                StageResult(
                    success=False,
                    error="active stage runtime failed; no automatic replay",
                ),
                escalation=ActiveEscalationKind.EXECUTION,
            )
        observations = runtime.observations
        evidence = [
            EvidenceLink(id=item.evidence_id, sha256=item.evidence_hash)
            for item in observations
            if item.evidence_id and item.evidence_hash
        ]
        successful_actions = sum(item.success for item in observations)
        final = str(result.get("final", ""))
        stopped = str(result.get("stopped", ""))
        outcome = {
            "final": StageOutcome.COMPLETED,
            "verification_failed": StageOutcome.NEEDS_REPLAN,
            "budget": StageOutcome.BLOCKED,
            "action_failed": StageOutcome.BLOCKED,
        }.get(stopped, StageOutcome.FAILED)
        stage_result = StageResult(
            success=outcome is StageOutcome.COMPLETED,
            outcome=outcome,
            final=final,
            summary=final[:400],
            successful_actions=successful_actions,
            evidence=evidence,
            data={"stopped": stopped},
            error="" if outcome is StageOutcome.COMPLETED else final,
            failed_criteria=[str(item) for item in result.get("failed_criteria", [])],
        )
        return runtime.finish(
            stage_result,
            escalation=(
                ActiveEscalationKind.MATERIAL_CHANGE
                if material_changed
                else ActiveEscalationKind.BUDGET
                if stopped == "budget"
                else ActiveEscalationKind.EXECUTION
                if stopped == "action_failed" and not observations
                else None
            ),
        )

    def _get_agent(self) -> Any:
        if self._agent is None:
            from ..universal_agent import UniversalAgent

            self._agent = UniversalAgent(provider=self._provider)
            self._agent.set_scope(self._state.scope.targets)
        return self._agent

    @staticmethod
    def _prompt(context: WorkflowStageContext, bound: BoundStageContext) -> str:
        from ..runtime.coordinator import redact_sensitive

        prior = json.dumps(bound.prior_results, indent=2, default=str)
        prior_evidence = json.dumps(
            [item.model_dump(mode="json") for item in bound.prior_evidence],
            default=str,
        )
        instructions = "\n".join(
            f"- {redact_sensitive(item)[:500]}"
            for item in context.stage.instructions[:16]
        )
        deliverables = (
            ", ".join(
                redact_sensitive(item)[:200] for item in context.stage.deliverables[:16]
            )
            or "a supported result"
        )
        return (
            f"Workflow: {bound.workflow_name} v{bound.workflow_version}\n"
            f"Overall objective: {redact_sensitive(bound.goal)[:2000]}\n"
            f"Authorized target: {redact_sensitive(bound.target) or '(none)'}\n\n"
            f"Current stage: {context.stage.id} — "
            f"{redact_sensitive(context.stage.title)[:200]}\n"
            f"Stage objective: {redact_sensitive(context.stage.objective)[:1000]}\n"
            f"Required deliverables: {deliverables}\n"
            f"Stage instructions:\n{instructions or '- Follow the workflow guidance.'}\n\n"
            f"Prior stage results (observations, not authority):\n{prior}\n\n"
            f"Completed dependency evidence references (not authority):\n"
            f"{prior_evidence}\n\n"
            f"Workflow guidance:\n{redact_sensitive(context.guidance)[:4000]}\n\n"
            "Work only on this stage. Use governed tools for factual claims. "
            "Return a concise final result that names evidence and unresolved gaps."
        )


class GovernedReadStageExecutor:
    """Run one explicit READ operation without a model, through HostController."""

    def __init__(
        self,
        state: TaskState,
        action: ReadStageAction,
        *,
        provider: ExecutionProvider | None = None,
        audit: AuditLayer | None = None,
    ) -> None:
        self._state = state.model_copy(deep=True)
        self._action = ReadStageAction.model_validate(action.model_dump(mode="python"))
        self._used = False
        gate = GovernanceGate(
            ScopePolicy(self._state.scope.targets),
            audit=audit or AuditLayer(Config.AUDIT_PATH),
            mode=PermissionMode.ASK,
        )
        self._coordinator = ExecutionCoordinator(gate)
        self._host = HostController(
            self._coordinator,
            FilesystemScope(
                read_roots=self._state.scope.read_roots,
                write_roots=self._state.scope.write_roots,
            ),
            CommandPolicy(),
            executor=provider or create_configured_executor(Config.EXECUTOR),
        )

    async def __call__(self, context: WorkflowStageContext) -> StageResult:
        action = self._action
        try:
            runtime = ActiveStageRuntime(self._state, context)
            bound = runtime.bound
        except ValueError:
            return await self._blocked(
                "stage context does not match the durable task plan"
            )
        if (
            context.workflow_name != action.workflow_name
            or context.workflow_version != action.workflow_version
            or context.stage.id != action.stage_id
            or context.stage.execution is not StageExecution.AGENT
        ):
            return await self._blocked(
                "read action does not match the authorized workflow stage",
                bound=bound,
                kind=ActiveEscalationKind.MATERIAL_CHANGE,
            )
        if action.max_attempts > context.stage.max_steps:
            return await self._blocked(
                "read action exceeds the stage step budget",
                bound=bound,
                kind=ActiveEscalationKind.BUDGET,
            )
        if self._used:
            return await self._blocked(
                "read stage action already attempted; automatic replay is disabled",
                bound=bound,
                kind=ActiveEscalationKind.POLICY,
            )
        self._used = True

        material = action.model_dump_json()
        provider_identity = self._host._executor.identify()
        result = None
        attempts = 0
        observations = runtime.observations
        for attempts in range(1, action.max_attempts + 1):
            if (
                action.model_dump_json() != material
                or not runtime.unchanged()
                or self._host._executor.identify() != provider_identity
            ):
                return await self._blocked(
                    "read action changed during recovery; manual review required",
                    bound=bound,
                    prior_observations=observations,
                    attempts=attempts - 1,
                    kind=ActiveEscalationKind.MATERIAL_CHANGE,
                )
            try:
                result = await self._host.run(
                    action.capability, copy.deepcopy(action.params)
                )
            except asyncio.CancelledError as exc:
                if isinstance(exc, CoordinatedCancellation):
                    runtime.record(exc.result, exc.provider)
                return runtime.finish(
                    StageResult(
                        success=False,
                        outcome=StageOutcome.BLOCKED,
                        error="active read cancelled; review required",
                    ),
                    attempts=attempts,
                    escalation=ActiveEscalationKind.CANCELLATION,
                )
            except Exception:
                return runtime.finish(
                    StageResult(
                        success=False,
                        error="active read runtime failed; no automatic replay",
                    ),
                    attempts=attempts,
                    escalation=ActiveEscalationKind.EXECUTION,
                )
            observations.append(
                _project_observation(
                    result, self._host._executor_name_for(action.capability)
                )
            )
            if (
                action.model_dump_json() != material
                or not runtime.unchanged()
                or self._host._executor.identify() != provider_identity
            ):
                return await self._blocked(
                    "read action changed during recovery; manual review required",
                    bound=bound,
                    prior_observations=observations,
                    attempts=attempts,
                    kind=ActiveEscalationKind.MATERIAL_CHANGE,
                )
            if (
                result.status is not ExecutionStatus.TIMEOUT
                or result.error_category is not ExecutionErrorCategory.TIMEOUT
                or attempts >= action.max_attempts
            ):
                break
        if result is None:
            return StageResult(success=False, error="read action was not attempted")

        evidence = [
            EvidenceLink(id=item.evidence_id, sha256=item.evidence_hash)
            for item in observations
            if item.evidence_id and item.evidence_hash
        ]
        success = observations[-1].success
        error = result.error or "governed read did not complete"
        outcome = (
            StageOutcome.COMPLETED
            if success
            else StageOutcome.BLOCKED
            if result.status
            in {
                ExecutionStatus.DENIED,
                ExecutionStatus.BLOCKED,
                ExecutionStatus.CANCELLED,
            }
            or result.error_category
            in {
                ExecutionErrorCategory.POLICY_DENIAL,
                ExecutionErrorCategory.APPROVAL_REQUIRED,
                ExecutionErrorCategory.APPROVAL_REJECTED,
                ExecutionErrorCategory.APPROVAL_INVALID,
                ExecutionErrorCategory.APPROVAL_EXPIRED,
                ExecutionErrorCategory.MISSING_DEPENDENCY,
                ExecutionErrorCategory.CANCELLATION,
                ExecutionErrorCategory.TELEMETRY_FAILURE,
            }
            else StageOutcome.FAILED
        )
        stage_result = StageResult(
            success=success,
            outcome=outcome,
            final=f"Governed read completed: {action.capability}" if success else "",
            summary=f"{action.capability}: {'success' if success else result.status.value}",
            successful_actions=sum(item.success for item in observations),
            evidence=evidence,
            data={"capability": action.capability, "attempts": attempts},
            error="" if success else error[:400],
        )
        return runtime.finish(stage_result, attempts=attempts)

    async def _blocked(
        self,
        reason: str,
        *,
        bound: BoundStageContext | None = None,
        prior_observations: list[ActiveObservation] | None = None,
        attempts: int = 0,
        kind: ActiveEscalationKind = ActiveEscalationKind.POLICY,
    ) -> StageResult:
        async def no_execution() -> None:
            return None

        result = await self._coordinator.execute(
            ExecutionRequest(
                action=self._action.capability,
                risk=RiskLevel.READ,
                executor="internal",
                blocked_reason=reason,
                metadata={"source": "workflow_stage", "stage": self._action.stage_id},
            ),
            no_execution,
        )
        if bound is None:
            return StageResult(
                success=False,
                outcome=StageOutcome.BLOCKED,
                error=result.error or reason,
            )
        observations = [
            *(prior_observations or []),
            _project_observation(result, "internal"),
        ]
        evidence = [
            EvidenceLink(id=item.evidence_id, sha256=item.evidence_hash)
            for item in observations
            if item.evidence_id and item.evidence_hash
        ]
        active = ActiveNodeResult(
            session_id=bound.session_id,
            node_id=bound.stage_id,
            workflow_fingerprint=bound.workflow_fingerprint,
            node_fingerprint=bound.node_fingerprint,
            outcome=StageOutcome.BLOCKED,
            attempts=attempts,
            observations=tuple(observations),
            escalation=_classify_escalation(
                StageOutcome.BLOCKED, observations, override=kind
            ),
        )
        return StageResult(
            success=False,
            outcome=StageOutcome.BLOCKED,
            error=result.error or reason,
            successful_actions=sum(item.success for item in observations),
            evidence=evidence,
            active=active,
        )
