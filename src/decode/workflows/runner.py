"""Durable workflow runner with deterministic stage transitions and gates."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from ..persistence.manager import SessionManager
from ..planner import PlanGraph
from ..schema import ActiveEscalationKind, ScopeView, TaskState, TaskStatus
from ..schema.store import TaskStateStore
from .agent_executor import ActiveStageRuntime
from .models import (
    CoreBudgetState,
    CoreIntent,
    CoreMissionBudget,
    CoreMissionStop,
    CoreReplanOrigin,
    CoreReplanTransition,
    CoreReviewResolution,
    CoreStageDecision,
    CoreStrategy,
    CoreWorkflowSelection,
    ReviewedWorkflow,
    StageExecution,
    StageOutcome,
    StageResult,
    WorkflowRunReport,
    WorkflowSpec,
    WorkflowStage,
    WorkflowStageContext,
    core_state_fingerprint,
)
from .registry import CoreWorkflowPlanner, WorkflowRegistry

StageExecutor = Callable[[WorkflowStageContext], StageResult | Awaitable[StageResult]]


class WorkflowRunner:
    """Compile, persist, and advance workflows through one narrow interface."""

    def __init__(
        self,
        registry: WorkflowRegistry | None = None,
        sessions: SessionManager | None = None,
    ) -> None:
        self.registry = registry or WorkflowRegistry()
        self.sessions = sessions or SessionManager()
        self._states = TaskStateStore(self.sessions.store)

    def start(
        self,
        workflow_name: str,
        goal: str,
        *,
        target: str = "",
        read_roots: list[str] | None = None,
        write_roots: list[str] | None = None,
    ) -> WorkflowRunReport:
        spec = self._require_spec(workflow_name)
        return self._start(spec, goal, target, read_roots, write_roots)

    def start_core(
        self,
        intent: CoreIntent,
        reviewed: tuple[ReviewedWorkflow, ...],
        *,
        target: str = "",
        read_roots: list[str] | None = None,
        write_roots: list[str] | None = None,
        budget: CoreMissionBudget | None = None,
    ) -> WorkflowRunReport:
        from ..runtime.coordinator import redact_sensitive

        intent = CoreIntent.model_validate(intent.model_dump())
        if budget is not None:
            budget = CoreMissionBudget.model_validate(budget.model_dump())
        selection = CoreWorkflowPlanner(self.registry).select(intent, reviewed)
        if selection.outcome != "selected" or selection.workflow is None:
            raise ValueError(selection.public_reason)
        spec = self._require_spec(selection.workflow.name).model_copy(deep=True)
        if spec.fingerprint() != selection.workflow.fingerprint:
            raise ValueError("reviewed workflow changed before plan creation")
        return self._start(
            spec,
            redact_sensitive(intent.objective),
            target,
            read_roots,
            write_roots,
            selection,
            budget,
        )

    def _start(
        self,
        spec: WorkflowSpec,
        goal: str,
        target: str,
        read_roots: list[str] | None,
        write_roots: list[str] | None,
        selection: CoreWorkflowSelection | None = None,
        budget: CoreMissionBudget | None = None,
        *,
        budget_state: CoreBudgetState | None = None,
        origin: CoreReplanOrigin | None = None,
        inherited_task: TaskState | None = None,
    ) -> WorkflowRunReport:
        if spec.target_required and not target.strip():
            raise ValueError(f"workflow '{spec.name}' requires an explicit target")
        strategy = CoreStrategy.from_spec(spec) if selection is not None else None
        session_id = self.sessions.create(goal=goal, target_focus=target)
        state = TaskState(
            session_id=session_id,
            objective=goal,
            mode=spec.mode,
            scope=ScopeView(
                read_roots=read_roots or [],
                write_roots=write_roots or [],
                targets=[target] if target else [],
                allow_destructive=False,
            ),
            plan=spec.to_plan(goal),
            environment={
                "workflow": spec.name,
                "workflow_version": spec.version,
                "workflow_fingerprint": spec.fingerprint(),
                "target": target,
            },
        )
        if selection is not None:
            state.environment["core_selection"] = selection.model_dump(mode="json")
            state.environment["core_strategy"] = strategy.model_dump(mode="json")
        if budget is not None:
            state.environment["core_budget"] = CoreBudgetState(
                limits=budget
            ).model_dump(mode="json")
        if budget_state is not None:
            state.environment["core_budget"] = budget_state.model_dump(mode="json")
        if origin is not None:
            state.environment["core_replan_origin"] = origin.model_dump(mode="json")
        if inherited_task is not None:
            state.scope = inherited_task.scope.model_copy(deep=True)
            state.constraints = list(inherited_task.constraints)
            state.completion_conditions = [
                item.model_copy(deep=True)
                for item in inherited_task.completion_conditions
            ]
        self._save_plan(state)
        self._states.save(state)
        return self._report(state, spec, message="workflow created")

    def status(self, session_id: str) -> WorkflowRunReport:
        state, spec = self._load(session_id)
        return self._report(state, spec)

    def load_state(self, session_id: str) -> TaskState:
        """Return the durable state used to configure a governed stage executor."""
        state, _ = self._load(session_id)
        return state

    def decide_core(self, session_id: str) -> CoreStageDecision:
        state, spec = self._load(session_id)
        decision = CoreWorkflowPlanner(self.registry).decide(state, spec)
        state.environment["core_decision"] = decision.model_dump(mode="json")
        state.environment["core_decision_consumed"] = False
        self._states.save(state)
        return decision

    def issued_core(self, session_id: str, fingerprint: str) -> CoreStageDecision:
        state, spec = self._load(session_id)
        decision = CoreStageDecision.model_validate(
            state.environment.get("core_decision")
        )
        if decision.fingerprint() != fingerprint:
            raise ValueError(
                "Core decision identifier does not match the issued decision"
            )
        self._validate_core_decision(state, spec, decision)
        return decision

    async def run_core(
        self, decision: CoreStageDecision, executor: StageExecutor
    ) -> WorkflowRunReport:
        decision = CoreStageDecision.model_validate(decision.model_dump())
        return await self._advance(
            decision.session_id, executor, core_decision=decision
        )

    def approve_core_stage(self, decision: CoreStageDecision) -> WorkflowRunReport:
        decision = CoreStageDecision.model_validate(decision.model_dump())
        state, spec = self._load(decision.session_id)
        self._validate_core_decision(state, spec, decision)
        if decision.outcome != "await_approval":
            raise ValueError(
                "explicit Core gate approval requires an awaiting-human decision"
            )
        state.environment["core_decision_consumed"] = True
        self._states.save(state)
        if state.plan.nodes[decision.stage_id].status == "pending":
            self._checkpoint(
                state, decision.stage_id, "needs_review", decision.public_reason
            )
        self._approve_human_stage(state, spec, decision.stage_id)
        return self._report(
            state,
            spec,
            message="human workflow gate approved; request a fresh Core decision",
        )

    def _validate_core_decision(
        self, state: TaskState, spec: WorkflowSpec, decision: CoreStageDecision
    ) -> None:
        try:
            issued = CoreStageDecision.model_validate(
                state.environment.get("core_decision")
            )
        except ValueError:
            raise ValueError("Core decision was not issued for this task") from None
        expected = CoreWorkflowPlanner(self.registry).decide(state, spec)
        if (
            state.environment.get("core_decision_consumed") is not False
            or issued != decision
            or expected != decision
        ):
            raise ValueError("Core decision is stale, altered, or already consumed")

    def review_core(self, resolution: CoreReviewResolution) -> WorkflowRunReport:
        resolution = CoreReviewResolution.model_validate(resolution.model_dump())
        decision = resolution.decision
        state, spec = self._load(decision.session_id)
        self._validate_core_decision(state, spec, decision)
        state.environment["core_decision_consumed"] = True
        state.environment["core_review_resolution"] = resolution.model_dump(mode="json")
        state.mark(
            TaskStatus.FAILED if decision.outcome == "failed" else TaskStatus.BLOCKED
        )
        self._states.save(state)
        return self._report(
            state,
            spec,
            message=f"Core review {resolution.disposition}; mission remains stopped; no changes applied",
        )

    def stop_core(self, decision: CoreStageDecision) -> WorkflowRunReport:
        decision = CoreStageDecision.model_validate(decision.model_dump())
        state, spec = self._load(decision.session_id)
        self._validate_core_decision(state, spec, decision)
        state.environment["core_stop"] = CoreMissionStop(decision=decision).model_dump(
            mode="json"
        )
        state.environment["core_decision_consumed"] = True
        if state.status not in {TaskStatus.COMPLETE, TaskStatus.FAILED}:
            state.mark(TaskStatus.BLOCKED)
        else:
            state._touch()
        self._states.save(state)
        return self._report(
            state,
            spec,
            message="mission explicitly stopped by human; no automatic resume",
        )

    def replan_core(
        self,
        decision: CoreStageDecision,
        intent: CoreIntent,
        reviewed: tuple[ReviewedWorkflow, ...],
    ) -> WorkflowRunReport:
        decision = CoreStageDecision.model_validate(decision.model_dump())
        intent = CoreIntent.model_validate(intent.model_dump())
        state, spec = self._load(decision.session_id)
        self._validate_core_decision(state, spec, decision)
        if decision.review_request is None or "core_stop" in state.environment:
            raise ValueError("Core replanning requires an unresolved review stop")
        if state.unresolved_questions:
            raise ValueError(
                "unanswered mission input must be resolved before replanning"
            )
        if state.environment.get("core_dispatch_pending") or any(
            node.status == "running" for node in state.plan.nodes.values()
        ):
            raise ValueError(
                "interrupted or running work must be reconciled before replanning"
            )
        if (
            intent.fingerprint()
            != CoreIntent(objective=state.objective, mode=state.mode).fingerprint()
        ):
            raise ValueError(
                "Core replanning cannot change the mission objective or mode"
            )
        if self._validate_core_lineage(state) >= 32:
            raise ValueError("Core replacement lineage is bounded to 32 transitions")
        selection = CoreWorkflowPlanner(self.registry).select(intent, reviewed)
        if selection.outcome != "selected" or selection.workflow is None:
            raise ValueError(selection.public_reason)
        replacement = self._require_spec(selection.workflow.name).model_copy(deep=True)
        if replacement.fingerprint() != selection.workflow.fingerprint:
            raise ValueError("reviewed replacement changed before plan creation")
        CoreStrategy.from_spec(replacement)
        if (
            replacement.target_required
            and not str(state.environment.get("target", "")).strip()
        ):
            raise ValueError(
                "reviewed replacement requires an existing authorized target"
            )
        budget = (
            CoreBudgetState.model_validate(state.environment["core_budget"])
            if "core_budget" in state.environment
            else None
        )
        transition = CoreReplanTransition(decision=decision, replacement=selection)
        state.environment["core_replan_transition"] = transition.model_dump(mode="json")
        state.environment["core_stop"] = CoreMissionStop(decision=decision).model_dump(
            mode="json"
        )
        state.environment["core_decision_consumed"] = True
        if state.status is not TaskStatus.FAILED:
            state.mark(TaskStatus.BLOCKED)
        else:
            state._touch()
        self._states.save(state)
        created = self._start(
            replacement,
            state.objective,
            str(state.environment.get("target", "")),
            list(state.scope.read_roots),
            list(state.scope.write_roots),
            selection,
            budget_state=budget,
            origin=CoreReplanOrigin(
                parent_session_id=state.session_id,
                decision_fingerprint=decision.fingerprint(),
            ),
            inherited_task=state,
        )
        state.environment["core_replan_transition"] = CoreReplanTransition(
            decision=decision,
            replacement=selection,
            replacement_session_id=created.session_id,
        ).model_dump(mode="json")
        state._touch()
        self._states.save(state)
        return created.model_copy(update={"message": transition.public_reason})

    async def run(
        self,
        session_id: str,
        executor: StageExecutor,
        *,
        approve_stage: str = "",
    ) -> WorkflowRunReport:
        return await self._advance(session_id, executor, approve_stage=approve_stage)

    async def _advance(
        self,
        session_id: str,
        executor: StageExecutor,
        *,
        approve_stage: str = "",
        core_decision: CoreStageDecision | None = None,
    ) -> WorkflowRunReport:
        state, spec = self._load(session_id)
        reserved_budget: CoreBudgetState | None = None
        if core_decision is not None:
            self._validate_core_decision(state, spec, core_decision)
            state.environment["core_decision_consumed"] = True
            if core_decision.outcome != "delegate":
                if core_decision.outcome == "await_approval":
                    self._checkpoint(
                        state,
                        core_decision.stage_id,
                        "needs_review",
                        core_decision.public_reason,
                    )
                if core_decision.outcome == "stopped" and state.status in {
                    TaskStatus.COMPLETE,
                    TaskStatus.FAILED,
                }:
                    state._touch()
                else:
                    state.mark(
                        TaskStatus.COMPLETE
                        if core_decision.outcome == "complete"
                        else TaskStatus.FAILED
                        if core_decision.outcome == "failed"
                        else TaskStatus.BLOCKED
                    )
                self._states.save(state)
                if state.status is TaskStatus.COMPLETE:
                    self.sessions.close(session_id)
                return self._report(state, spec, message=core_decision.public_reason)
            state.environment["core_dispatch_pending"] = core_decision.stage_id
            if "core_budget" in state.environment:
                reserved_budget = CoreBudgetState.model_validate(
                    state.environment["core_budget"]
                ).reserve(core_decision.max_steps)
                state.environment["core_budget"] = reserved_budget.model_dump(
                    mode="json"
                )
                state._touch()
            self._states.save(state)
        elif "core_stop" in state.environment:
            raise ValueError("stopped Core mission cannot resume automatically")
        elif state.environment.get("core_dispatch_pending"):
            raise ValueError(
                "interrupted Core handoff requires review; no automatic replay"
            )
        elif "core_budget" in state.environment:
            raise ValueError("budgeted Core missions require the bounded run_core path")
        elif (
            "core_selection" in state.environment
            and CoreWorkflowPlanner(self.registry).decide(state, spec).review_request
            is not None
        ):
            raise ValueError(
                "Core review stop cannot be bypassed by compatibility execution"
            )
        interrupted = self.sessions.store.recover_interrupted_plan(session_id)
        if interrupted:
            state, spec = self._load(session_id)
            state.mark(TaskStatus.BLOCKED)
            self._states.save(state)
            return self._report(
                state,
                spec,
                message="interrupted stages require review; automatic retry is disabled: "
                + ", ".join(interrupted),
            )

        if approve_stage:
            self._approve_human_stage(state, spec, approve_stage)

        while True:
            ready = state.plan.ready_nodes()
            if not ready:
                break
            node = (
                state.plan.nodes[core_decision.stage_id]
                if core_decision is not None
                else ready[0]
            )
            if node not in ready:
                raise ValueError("Core delegated stage is no longer ready")
            stage = spec.stage(node.id)
            if stage.execution is StageExecution.HUMAN:
                self._checkpoint(
                    state,
                    stage.id,
                    "needs_review",
                    "explicit human approval required",
                )
                state.mark(TaskStatus.BLOCKED)
                self._states.save(state)
                return self._report(
                    state,
                    spec,
                    message=f"stage '{stage.id}' requires explicit approval",
                )

            self._checkpoint(state, stage.id, "running", increment_attempts=True)
            state.record_action(
                f"workflow:{stage.id}",
                {"workflow": spec.name, "stage": stage.id},
                f"execute deterministic workflow stage {stage.id}",
            )
            context = self._context(state, spec, stage)
            if core_decision is not None:
                context = context.model_copy(deep=True)
            working_state = (
                state.model_copy(deep=True) if core_decision is not None else state
            )
            core_snapshot = (
                core_state_fingerprint(working_state)
                if core_decision is not None
                else ""
            )
            runtime = ActiveStageRuntime(working_state, context.model_copy(deep=True))
            try:
                bind_state = getattr(executor, "bind_state", None)
                if callable(bind_state):
                    bind_state(working_state)
                result = executor(context)
                if inspect.isawaitable(result):
                    result = await result
                result = StageResult.model_validate(result)
                if core_decision is not None and result.active is None:
                    result = runtime.finish(result)
            except asyncio.CancelledError:
                result = runtime.finish(
                    StageResult(
                        success=False,
                        outcome=StageOutcome.BLOCKED,
                        error="workflow stage cancelled; review required",
                    ),
                    escalation=ActiveEscalationKind.CANCELLATION,
                )
            except Exception:
                result = runtime.finish(
                    StageResult(
                        success=False,
                        error="stage executor failed; no automatic replay",
                        summary="stage executor failed",
                    ),
                    escalation=ActiveEscalationKind.EXECUTION,
                )
            core_changed = False
            if core_decision is not None:
                try:
                    core_changed = (
                        core_state_fingerprint(working_state) != core_snapshot
                    )
                except (TypeError, ValueError):
                    core_changed = True
            if core_decision is not None and (
                core_changed
                or not runtime.unchanged()
                or spec.fingerprint() != core_decision.workflow_fingerprint
                or context.model_dump(mode="json")
                != runtime._context.model_dump(mode="json")
            ):
                result = runtime.finish(
                    StageResult(
                        success=False,
                        outcome=StageOutcome.BLOCKED,
                        error="delegated Active envelope changed; review required",
                    ),
                    escalation=ActiveEscalationKind.MATERIAL_CHANGE,
                )
            if result.active is not None and (
                result.active.session_id != state.session_id
                or result.active.node_id != stage.id
                or result.active.workflow_fingerprint
                != state.environment.get("workflow_fingerprint")
                or result.active.node_fingerprint
                != state.plan.nodes[stage.id].material_fingerprint()
            ):
                result = runtime.finish(
                    StageResult(
                        success=False,
                        outcome=StageOutcome.BLOCKED,
                        error="active result does not match the durable workflow node",
                    ),
                    escalation=ActiveEscalationKind.MATERIAL_CHANGE,
                )
            if (
                core_decision is not None
                and result.active is not None
                and result.active.attempts > core_decision.max_steps
            ):
                result = runtime.finish(
                    StageResult(
                        success=False,
                        outcome=StageOutcome.BLOCKED,
                        error="Active result exceeded delegated stage bounds",
                    ),
                    escalation=ActiveEscalationKind.BUDGET,
                )
            gate_ok, failures = stage.gate.check(result)
            if result.active is not None and result.active.gate_passed != gate_ok:
                result = runtime.finish(
                    StageResult(
                        success=False,
                        outcome=StageOutcome.BLOCKED,
                        error="active result gate differs from durable workflow gate",
                    ),
                    escalation=ActiveEscalationKind.VERIFICATION,
                )
                gate_ok, failures = stage.gate.check(result)
            if reserved_budget is not None:
                state.environment["core_budget"] = reserved_budget.model_dump(
                    mode="json"
                )
            self._record_result(state, stage, result)
            if core_decision is not None:
                state.environment.pop("core_dispatch_pending", None)
            if gate_ok:
                self._checkpoint(
                    state, stage.id, "success", result.summary or result.final
                )
                if core_decision is not None and any(
                    item.status != "success" for item in state.plan.nodes.values()
                ):
                    state.mark(TaskStatus.INVESTIGATING)
                    self._states.save(state)
                    return self._report(
                        state,
                        spec,
                        message="one Core stage completed; request a fresh decision",
                    )
                continue
            reason = "; ".join(failures)
            if result.outcome in {StageOutcome.NEEDS_REPLAN, StageOutcome.BLOCKED}:
                self._checkpoint(state, stage.id, "needs_review", reason)
                state.mark(TaskStatus.BLOCKED)
                self._states.save(state)
                return self._report(state, spec, message=reason)
            self._checkpoint(state, stage.id, "error", reason)
            state.mark(TaskStatus.FAILED)
            self._states.save(state)
            return self._report(state, spec, message=reason)

        statuses = {node.status for node in state.plan.nodes.values()}
        if statuses <= {"success", "skipped"}:
            completion = (
                CoreWorkflowPlanner(self.registry).decide(state, spec)
                if "core_selection" in state.environment
                else None
            )
            if completion is not None and completion.outcome != "complete":
                state.mark(TaskStatus.BLOCKED)
                message = completion.public_reason
            else:
                state.mark(TaskStatus.COMPLETE)
                self.sessions.close(session_id)
                message = "workflow complete"
        elif "needs_review" in statuses:
            state.mark(TaskStatus.BLOCKED)
            message = "workflow paused for review"
        elif "error" in statuses:
            state.mark(TaskStatus.FAILED)
            message = "workflow failed"
        else:
            state.mark(TaskStatus.BLOCKED)
            message = "workflow has no runnable stage"
        self._states.save(state)
        return self._report(state, spec, message=message)

    def _approve_human_stage(
        self, state: TaskState, spec: WorkflowSpec, stage_id: str
    ) -> None:
        stage = spec.stage(stage_id)
        node = state.plan.nodes[stage_id]
        if stage.execution is not StageExecution.HUMAN:
            raise ValueError(f"stage '{stage_id}' is not a human approval stage")
        if node.status != "needs_review":
            raise ValueError(f"stage '{stage_id}' is not awaiting approval")
        if not all(
            state.plan.nodes[item].status == "success" for item in node.depends_on
        ):
            raise ValueError(f"stage '{stage_id}' dependencies are not complete")
        state.record_action(
            f"workflow:{stage_id}", {"approved": True}, "human approval"
        )
        state.record_observation(
            f"workflow:{stage_id}",
            {
                "success": True,
                "summary": "approved by human",
                "data": {"approved": True},
            },
        )
        self._checkpoint(state, stage_id, "success", "approved by human")
        state.mark(TaskStatus.INVESTIGATING)
        self._states.save(state)

    def _context(
        self, state: TaskState, spec: WorkflowSpec, stage: WorkflowStage
    ) -> WorkflowStageContext:
        prior: list[dict[str, Any]] = []
        for observation in state.observations[-8:]:
            if not observation.tool.startswith("workflow:"):
                continue
            prior.append(
                {
                    "stage": observation.tool.split(":", 1)[1],
                    "success": observation.success,
                    "summary": observation.summary,
                    "final": str(observation.data.get("final", ""))[:4000],
                }
            )
        return WorkflowStageContext(
            session_id=state.session_id,
            workflow_name=spec.name,
            workflow_version=spec.version,
            goal=state.objective,
            target=str(state.environment.get("target", "")),
            stage=stage,
            guidance=spec.guidance,
            prior_results=prior,
        )

    def _record_result(
        self, state: TaskState, stage: WorkflowStage, result: StageResult
    ) -> None:
        if result.active is not None:
            state.active_nodes[stage.id] = result.active
        first = result.evidence[0] if result.evidence else None
        state.record_observation(
            f"workflow:{stage.id}",
            {
                "success": result.success,
                "summary": result.summary or result.final[:400],
                "data": {
                    "final": result.final,
                    "successful_actions": result.successful_actions,
                    "outcome": result.outcome.value,
                    "failed_criteria": result.failed_criteria,
                    **result.data,
                },
                "evidence": ({"id": first.id, "sha256": first.sha256} if first else {}),
            },
        )
        for link in result.evidence[1:]:
            state.add_artifact(
                source=f"workflow:{stage.id}",
                action=stage.id,
                related_step=len(state.observations),
                summary=link.summary or result.summary,
                evidence_id=link.id,
                evidence_hash=link.sha256,
            )
        self._states.save(state)

    def _checkpoint(
        self,
        state: TaskState,
        stage_id: str,
        status: str,
        summary: str = "",
        *,
        increment_attempts: bool = False,
    ) -> None:
        state.plan.mark(stage_id, status, summary[:500])
        state._touch()
        self.sessions.store.checkpoint_plan_node(
            state.session_id,
            stage_id,
            status,
            summary[:500],
            increment_attempts=increment_attempts,
        )
        self._states.save(state)

    def _save_plan(self, state: TaskState) -> None:
        payload = state.plan.model_dump(mode="json")
        for node_id, node in state.plan.nodes.items():
            payload["nodes"][node_id]["material_fingerprint"] = (
                node.material_fingerprint()
            )
        self.sessions.store.save_plan(state.session_id, payload)

    def _load(self, session_id: str) -> tuple[TaskState, WorkflowSpec]:
        state = self._states.load(session_id)
        if state is None:
            raise ValueError(f"no workflow run found for session '{session_id}'")
        if "core_stop" in state.environment:
            stop = CoreMissionStop.model_validate(state.environment["core_stop"])
            if (
                "core_selection" not in state.environment
                or stop.decision.session_id != session_id
                or stop.decision.workflow_fingerprint
                != state.environment.get("workflow_fingerprint")
            ):
                raise ValueError("Core stop requires matching mission provenance")
        if "core_replan_transition" in state.environment:
            transition = CoreReplanTransition.model_validate(
                state.environment["core_replan_transition"]
            )
            if (
                "core_stop" not in state.environment
                or transition.decision != stop.decision
            ):
                raise ValueError("Core replacement requires a stopped parent mission")
        self._validate_core_lineage(state)
        if "core_review_resolution" in state.environment:
            resolution = CoreReviewResolution.model_validate(
                state.environment["core_review_resolution"]
            )
            if (
                "core_selection" not in state.environment
                or resolution.decision.session_id != session_id
                or resolution.decision.workflow_fingerprint
                != state.environment.get("workflow_fingerprint")
            ):
                raise ValueError(
                    "Core review resolution requires matching mission provenance"
                )
        if "core_budget" in state.environment:
            CoreBudgetState.model_validate(state.environment["core_budget"])
            if "core_selection" not in state.environment:
                raise ValueError(
                    "Core mission budgets require reviewed workflow provenance"
                )
        workflow_name = str(state.environment.get("workflow", ""))
        spec = self._require_spec(workflow_name)
        if state.environment.get("workflow_fingerprint") != spec.fingerprint():
            raise ValueError(
                "workflow definition changed since this run started; "
                "start a new run or restore the original definition"
            )
        persisted = self.sessions.store.load_plan(session_id)
        if persisted:
            state.plan = state.plan.model_validate(persisted)
        if "core_selection" in state.environment:
            selection = CoreWorkflowSelection.model_validate(
                state.environment["core_selection"]
            )
            expected = spec.to_plan(state.objective)

            def material(graph: PlanGraph) -> dict[str, Any]:
                return {
                    key: node.model_dump(exclude={"status", "result_summary"})
                    for key, node in graph.nodes.items()
                }

            if (
                selection.outcome != "selected"
                or selection.workflow is None
                or selection.workflow.name != spec.name
                or selection.workflow.version != spec.version
                or selection.workflow.fingerprint != spec.fingerprint()
                or selection.intent_fingerprint
                != CoreIntent(objective=state.objective, mode=state.mode).fingerprint()
                or state.mode != spec.mode
                or selection.criteria != {stage.id: stage.gate for stage in spec.stages}
                or state.plan.goal != state.objective
                or material(state.plan) != material(expected)
            ):
                raise ValueError(
                    "Core selection no longer matches the durable workflow plan"
                )
            if "core_strategy" in state.environment and CoreStrategy.model_validate(
                state.environment["core_strategy"]
            ) != CoreStrategy.from_spec(spec):
                raise ValueError(
                    "Core strategy no longer matches the reviewed workflow"
                )
        return state, spec

    def _validate_core_lineage(self, state: TaskState) -> int:
        visited = {state.session_id}
        depth = 0
        while "core_replan_origin" in state.environment:
            origin = CoreReplanOrigin.model_validate(
                state.environment["core_replan_origin"]
            )
            if origin.parent_session_id in visited or depth >= 32:
                raise ValueError(
                    "Core replacement lineage is cyclic or exceeds 32 transitions"
                )
            visited.add(origin.parent_session_id)
            depth += 1
            parent = self._states.load(origin.parent_session_id)
            if parent is None:
                raise ValueError("Core replacement parent is unavailable")
            transition = CoreReplanTransition.model_validate(
                parent.environment.get("core_replan_transition")
            )
            parent_stop = CoreMissionStop.model_validate(
                parent.environment.get("core_stop")
            )
            if (
                parent_stop.decision != transition.decision
                or transition.decision.session_id != parent.session_id
                or transition.decision.fingerprint() != origin.decision_fingerprint
                or transition.replacement_session_id != state.session_id
                or transition.replacement.model_dump(mode="json")
                != state.environment.get("core_selection")
                or parent_stop.decision.workflow_fingerprint
                != parent.environment.get("workflow_fingerprint")
                or state.objective != parent.objective
                or state.mode != parent.mode
                or state.scope != parent.scope
                or state.constraints != parent.constraints
                or state.completion_conditions != parent.completion_conditions
                or state.environment.get("target") != parent.environment.get("target")
                or ("core_budget" in parent.environment)
                != ("core_budget" in state.environment)
            ):
                raise ValueError("Core replacement lineage or authority changed")
            if "core_budget" in state.environment:
                inherited = CoreBudgetState.model_validate(
                    parent.environment["core_budget"]
                )
                current = CoreBudgetState.model_validate(
                    state.environment["core_budget"]
                )
                if (
                    current.limits != inherited.limits
                    or current.stage_dispatches < inherited.stage_dispatches
                    or current.reserved_steps < inherited.reserved_steps
                ):
                    raise ValueError(
                        "Core replacement cannot refund or expand inherited budget"
                    )
            state = parent
        return depth

    def _require_spec(self, name: str) -> WorkflowSpec:
        spec = self.registry.get(name)
        if spec is None:
            raise ValueError(f"unknown workflow '{name}'")
        return spec

    @staticmethod
    def _report(
        state: TaskState, spec: WorkflowSpec, message: str = ""
    ) -> WorkflowRunReport:
        nodes = state.plan.topological_order()
        return WorkflowRunReport(
            session_id=state.session_id,
            workflow=spec.name,
            workflow_version=spec.version,
            status=state.status.value,
            goal=state.objective,
            target=str(state.environment.get("target", "")),
            ready=[node.id for node in state.plan.ready_nodes()],
            completed=[node.id for node in nodes if node.status == "success"],
            failed=[node.id for node in nodes if node.status == "error"],
            needs_review=[node.id for node in nodes if node.status == "needs_review"],
            message=message,
        )
