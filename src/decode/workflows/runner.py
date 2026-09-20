"""Durable workflow runner with deterministic stage transitions and gates."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from ..persistence.manager import SessionManager
from ..schema import ScopeView, TaskState, TaskStatus
from ..schema.store import TaskStateStore
from .models import (
    StageExecution,
    StageResult,
    WorkflowRunReport,
    WorkflowSpec,
    WorkflowStage,
    WorkflowStageContext,
)
from .registry import WorkflowRegistry

StageExecutor = Callable[
    [WorkflowStageContext], StageResult | Awaitable[StageResult]
]


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
        if spec.target_required and not target.strip():
            raise ValueError(f"workflow '{spec.name}' requires an explicit target")
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

    async def run(
        self,
        session_id: str,
        executor: StageExecutor,
        *,
        approve_stage: str = "",
    ) -> WorkflowRunReport:
        state, spec = self._load(session_id)
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
            node = ready[0]
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
            try:
                result = executor(context)
                if inspect.isawaitable(result):
                    result = await result
                result = StageResult.model_validate(result)
            except Exception as exc:
                result = StageResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    summary="stage executor failed",
                )
            gate_ok, failures = stage.gate.check(result)
            self._record_result(state, stage, result)
            if gate_ok:
                self._checkpoint(state, stage.id, "success", result.summary or result.final)
                continue
            reason = "; ".join(failures)
            self._checkpoint(state, stage.id, "error", reason)
            state.mark(TaskStatus.FAILED)
            self._states.save(state)
            return self._report(state, spec, message=reason)

        statuses = {node.status for node in state.plan.nodes.values()}
        if statuses <= {"success", "skipped"}:
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
        if not all(state.plan.nodes[item].status == "success" for item in node.depends_on):
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
        first = result.evidence[0] if result.evidence else None
        state.record_observation(
            f"workflow:{stage.id}",
            {
                "success": result.success,
                "summary": result.summary or result.final[:400],
                "data": {
                    "final": result.final,
                    "successful_actions": result.successful_actions,
                    **result.data,
                },
                "evidence": (
                    {"id": first.id, "sha256": first.sha256} if first else {}
                ),
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
        return state, spec

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
