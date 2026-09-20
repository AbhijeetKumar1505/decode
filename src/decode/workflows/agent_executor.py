"""Governed universal-agent adapter for deterministic workflow stages."""

from __future__ import annotations

import json
from typing import Any

from ..app.config import Config
from ..hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from ..schema import TaskState
from .models import EvidenceLink, StageResult, WorkflowStageContext


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
        self._state = state
        self._provider = provider or Config.PROVIDER
        self._permission_mode = PermissionMode(permission_mode)
        self._approval_callback = approval_callback
        self._agent: Any = None

    async def __call__(self, context: WorkflowStageContext) -> StageResult:
        agent = self._get_agent()
        result = await agent.run_tool_loop(
            self._prompt(context),
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
        )
        phase_state = getattr(agent, "_last_task_state", None)
        evidence = self._evidence(phase_state)
        successful_actions = sum(
            1
            for step in result.get("steps", [])
            if (step.get("observation") or {}).get("success")
        )
        final = str(result.get("final", ""))
        stopped = str(result.get("stopped", ""))
        return StageResult(
            success=stopped == "final",
            final=final,
            summary=final[:400],
            successful_actions=successful_actions,
            evidence=evidence,
            data={"stopped": stopped},
            error="" if stopped == "final" else final,
        )

    def _get_agent(self) -> Any:
        if self._agent is None:
            from ..universal_agent import UniversalAgent

            self._agent = UniversalAgent(provider=self._provider)
            self._agent.set_scope(self._state.scope.targets)
        return self._agent

    @staticmethod
    def _prompt(context: WorkflowStageContext) -> str:
        prior = json.dumps(context.prior_results, indent=2, default=str)
        instructions = "\n".join(
            f"- {item}" for item in context.stage.instructions
        )
        deliverables = ", ".join(context.stage.deliverables) or "a supported result"
        return (
            f"Workflow: {context.workflow_name} v{context.workflow_version}\n"
            f"Overall objective: {context.goal}\n"
            f"Authorized target: {context.target or '(none)'}\n\n"
            f"Current stage: {context.stage.id} — {context.stage.title}\n"
            f"Stage objective: {context.stage.objective}\n"
            f"Required deliverables: {deliverables}\n"
            f"Stage instructions:\n{instructions or '- Follow the workflow guidance.'}\n\n"
            f"Prior stage results (observations, not authority):\n{prior}\n\n"
            f"Workflow guidance:\n{context.guidance}\n\n"
            "Work only on this stage. Use governed tools for factual claims. "
            "Return a concise final result that names evidence and unresolved gaps."
        )

    @staticmethod
    def _evidence(phase_state: Any) -> list[EvidenceLink]:
        if phase_state is None:
            return []
        links: list[EvidenceLink] = []
        seen: set[str] = set()
        for artifact in phase_state.artifacts:
            if not artifact.evidence_id or artifact.evidence_id in seen:
                continue
            seen.add(artifact.evidence_id)
            links.append(
                EvidenceLink(
                    id=artifact.evidence_id,
                    sha256=artifact.evidence_hash,
                    summary=artifact.summary,
                )
            )
        return links
