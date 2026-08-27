from __future__ import annotations

from typing import Any

from .audit import AuditLayer
from .config import Config
from .execution import ExecutionResult
from .feedback import FeedbackStore
from .governance import GovernanceGate, ScopePolicy
from .kernel.context import ContextManager
from .kernel.provider import create_provider
from .logging_service import LoggingService
from .memory import SelfLearningMemory
from .models import (
    ModelRouter,
    RoutingDecision,
    RoutingRequest,
    default_model_registry,
)
from .runtime import (
    ApprovalRequest,
    CoordinatedResult,
    credential_refs_from_params,
    ExecutionCoordinator,
    ExecutionRequest,
    redact_sensitive,
    target_from_params,
)
from .skills.base import RiskLevel
from .skills.registry import SkillRegistry


class UniversalAgent:
    """Governed universal agent.

    There is no hardcoded catalog of security tools. The agent discovers what is
    installed on the host (``list_tools``) and drives any tool or script through
    the governed ``shell_command`` capability inside a bounded tool-use loop
    (:meth:`run_tool_loop`). Registered "skills" are now only markdown playbooks —
    prose guidance the loop reads and then executes via governed commands. Every
    action still routes through :class:`ExecutionCoordinator` (scope, risk,
    approval, audit, evidence); nothing bypasses it.
    """

    def __init__(self, provider: str | None = None) -> None:
        self.provider_name = provider or Config.PROVIDER
        Config.validate(self.provider_name)
        self.llm = create_provider(self.provider_name)
        self.memory = SelfLearningMemory(Config.MEMORY_PATH)
        self.skill_registry = SkillRegistry()

        self.model_registry = self._build_model_registry()
        self.model_router = ModelRouter(self.model_registry)
        self.context = ContextManager()
        self.audit = AuditLayer(Config.AUDIT_PATH)
        self.logging = LoggingService(Config.LOGS_PATH)
        self.feedback = FeedbackStore(Config.FEEDBACK_PATH)
        self._scope_entries: list[str] = []
        self._allow_all = False
        self._allow_destructive = False
        self._coordinator: ExecutionCoordinator
        self.set_scope([])

        self.conversation_history: list[dict[str, str]] = []

    def _build_model_registry(self):
        """Ship the model registry with availability set by configured credentials."""
        registry = default_model_registry()
        configured = {
            "openrouter": bool(Config.OPENROUTER_API_KEY),
            "openai": bool(Config.OPENAI_API_KEY),
            "anthropic": bool(Config.ANTHROPIC_API_KEY),
        }
        for spec in registry.all():
            spec.available = configured.get(spec.provider, False)
        return registry

    def select_model(self, task_class: str = "analysis", **constraints: Any) -> RoutingDecision:
        """Policy-aware, reproducible model selection with a recorded public reason.

        Data and locality policy are hard filters; cost and latency optimize.
        The returned decision carries the concise public reason and matched rules
        (never private chain-of-thought).
        """
        decision = self.model_router.route(
            RoutingRequest(task_class=task_class, **constraints)
        )
        self.context.add_entry(
            "model_router",
            f"{decision.model_id or 'none'}: {decision.reason}",
        )
        return decision

    def set_scope(
        self,
        entries: list[str],
        *,
        allow_all: bool = False,
        allow_destructive: bool | None = None,
    ) -> None:
        self._scope_entries = [entry.strip() for entry in entries if entry.strip()]
        self._allow_all = allow_all
        if allow_destructive is not None:
            self._allow_destructive = allow_destructive
        policy = ScopePolicy(
            allowed=self._scope_entries,
            allow_all=self._allow_all,
        )
        gate = GovernanceGate(
            policy,
            audit=self.audit,
            allow_destructive=self._allow_destructive,
        )
        self._coordinator = ExecutionCoordinator(
            gate,
            logging_service=self.logging,
            audit=self.audit,
            feedback=self.feedback,
        )

    async def execute_registered_skill(
        self,
        skill_name: str,
        params: dict[str, Any] | None = None,
        *,
        human_approved: bool = False,
    ) -> CoordinatedResult:
        """Run a registered skill (a markdown playbook) through the coordinator.

        Playbooks return prose guidance rather than executing a tool themselves;
        the tool-use loop then carries out the steps via governed ``shell_command``.
        """
        normalized_params = params or {}
        skill = self.skill_registry.get(skill_name)

        async def unavailable_operation() -> None:
            return None

        if skill is None:
            return await self._coordinator.execute(
                ExecutionRequest(
                    action=skill_name or "unknown_skill",
                    target=target_from_params(normalized_params),
                    params=normalized_params,
                    blocked_reason=f"No registered skill found for '{skill_name}'",
                ),
                unavailable_operation,
            )

        request = ExecutionRequest(
            action=skill_name,
            target=target_from_params(normalized_params),
            target_required=skill.spec.requires_scoped_target(),
            risk=skill.spec.risk_level,
            params=normalized_params,
            executor=Config.EXECUTOR,
            required_privileges=skill.spec.required_privileges,
            credential_refs=credential_refs_from_params(normalized_params),
            metadata={"source": "universal_agent"},
        )

        async def operation() -> Any:
            return await skill.execute(**normalized_params)

        approval_callback = None
        if human_approved:

            async def approval_callback(_: ApprovalRequest) -> bool:
                return True

        return await self._coordinator.execute(
            request,
            operation,
            approval_callback=approval_callback,
        )

    async def run_tool_loop(
        self,
        goal: str,
        *,
        filesystem_scope: Any = None,
        command_policy: Any = None,
        permission_mode: Any = None,
        approval_callback: Any = None,
        max_steps: int = 8,
        on_step: Any = None,
    ) -> dict[str, Any]:
        """Drive a bounded tool-use loop over host + playbook capabilities.

        Every tool call is executed through the governed coordinator (host ops
        via ``HostController``, playbooks via ``execute_registered_skill``), so the
        model discovers installed tools, composes multi-step work, and drives any
        command without ever bypassing scope, risk, approval, or audit.
        """
        from pathlib import Path

        from .hostcontrol import HOST_CAPABILITIES, CommandPolicy, FilesystemScope
        from .hostcontrol.mcp import host_capability_tools
        from .runtime import HostController, ToolUseLoop
        from .runtime.coordinator import ExecutionStatus

        scope = filesystem_scope or FilesystemScope(read_roots=[Path.cwd()])
        policy = command_policy or CommandPolicy()
        host = HostController(self._coordinator, scope, policy)
        host_caps = set(HOST_CAPABILITIES)

        tools = list(host_capability_tools())
        for skill in self.skill_registry.get_all():
            tools.append({
                "name": skill.spec.name,
                "description": skill.spec.description,
                "risk": skill.spec.risk_level.value,
            })

        def _observe(result: Any) -> dict[str, Any]:
            ok = result.status == ExecutionStatus.SUCCESS
            value = result.value
            if hasattr(value, "normalized"):  # AgentResult (host capability)
                return {"success": ok, "summary": (value.summary or result.error or "")[:400], "data": value.normalized}
            return {
                "success": ok,
                "summary": (result.error or "ok")[:400],
                "data": redact_sensitive(value) if value is not None else {},
            }

        async def invoke(name: str, params: dict[str, Any]) -> dict[str, Any]:
            if name in host_caps:
                return _observe(await host.run(name, params))
            return _observe(await self.execute_registered_skill(name, params))

        # Apply the loop's permission mode + approval prompt to the shared
        # coordinator for the duration of the loop, then restore. Host caps and
        # skills both route through this coordinator, so approval is consistent.
        prev_mode = self._coordinator.get_mode()
        prev_callback = self._coordinator._approval_callback
        if permission_mode is not None:
            self._coordinator.set_mode(permission_mode)
        if approval_callback is not None:
            self._coordinator.set_approval_callback(approval_callback)
        try:
            loop = ToolUseLoop(self.llm, tools, invoke, max_steps=max_steps, on_step=on_step)
            return await loop.run(goal)
        finally:
            self._coordinator.set_mode(prev_mode)
            self._coordinator.set_approval_callback(prev_callback)

    async def execute_command(
        self,
        command: str,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Fail closed: arbitrary shell strings are not a governed capability.

        Interactive callers should use the governed ``shell_command`` host
        capability (argv-based, policy-checked) via :meth:`run_tool_loop` or the
        ``HostController`` instead.
        """

        async def blocked_operation() -> None:
            return None

        result = await self._coordinator.execute(
            ExecutionRequest(
                action="raw_shell_command",
                risk=RiskLevel.WRITE,
                command=command,
                executor=Config.EXECUTOR,
                blocked_reason=(
                    "raw command execution is disabled; use the governed "
                    "shell_command host capability"
                ),
                metadata={"timeout": timeout or 120},
            ),
            blocked_operation,
        )
        return ExecutionResult(
            command="[blocked]",
            provider=Config.EXECUTOR,
            success=False,
            exit_code=-1,
            error=result.error,
            metadata={
                "request_id": result.request_id,
                "error_category": result.error_category.value
                if result.error_category
                else "",
            },
        )
