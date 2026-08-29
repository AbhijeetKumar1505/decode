"""Governed invocation path for host-control capabilities.

Runs a single host capability through the ExecutionCoordinator with the
filesystem/command policy threaded into the agent context. For ad-hoc commands
the per-command risk is classified *before* the gate, so a WRITE command needs
approval and a DESTRUCTIVE one hits the destructive control — the capability's
baseline risk never under-gates a specific command.
"""

from __future__ import annotations

import shlex
from typing import Any

from ..agents.host import HostAgent
from ..capabilities import CAPABILITIES
from ..hostcontrol import CommandPolicy, FilesystemScope, HostSession
from ..hostcontrol.policy import RiskLevel as _HostRisk
from ..planner.dag import PlanNode
from ..skills.base import RiskLevel
from .coordinator import CoordinatedResult, ExecutionCoordinator, ExecutionRequest

_RISK_ORDER = {RiskLevel.READ: 0, RiskLevel.WRITE: 1, RiskLevel.DESTRUCTIVE: 2}
_SESSION_CAPABILITIES = ("session_open", "session_exec", "session_close")


class _InternalSpecRegistry:
    """Minimal registry: internal capabilities only need spec lookup."""

    def get_spec(self, capability: str):
        return CAPABILITIES.get(capability)


class HostController:
    def __init__(
        self,
        coordinator: ExecutionCoordinator,
        filesystem_scope: FilesystemScope | None = None,
        command_policy: CommandPolicy | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._registry = _InternalSpecRegistry()
        self._agent = HostAgent()
        self._scope = filesystem_scope or FilesystemScope()
        self._policy = command_policy
        # Persistent governed session (subsystem 12): a single HostSession whose
        # cwd/env persist across loop turns. Argv-governed — each command is
        # policy-classified and routed through the coordinator like shell_command.
        self._session: HostSession | None = None

    def set_scope(self, filesystem_scope: FilesystemScope, command_policy: CommandPolicy | None) -> None:
        self._scope = filesystem_scope
        self._policy = command_policy

    def _resolved_risk(self, capability: str, params: dict, baseline: RiskLevel) -> RiskLevel:
        if self._policy is None:
            return baseline
        if capability in ("shell_command", "session_exec"):
            argv = params.get("argv")
            if isinstance(argv, (list, tuple)) and argv:
                argv = [str(a) for a in argv]
            else:
                argv = shlex.split(params.get("command", "") or "")
            return _HostRisk(self._policy.classify(argv).value) if argv else baseline
        if capability == "host_session":
            import json

            try:
                steps = json.loads(params.get("commands", "[]"))
            except (json.JSONDecodeError, TypeError):
                return baseline
            worst = baseline
            for step in steps if isinstance(steps, list) else []:
                argv = step if isinstance(step, list) else shlex.split(str(step))
                if argv and _RISK_ORDER[self._policy.classify(argv)] > _RISK_ORDER[worst]:
                    worst = self._policy.classify(argv)
            return worst
        return baseline

    async def run(self, capability: str, params: dict[str, Any] | None = None, *, stdin: str | None = None) -> CoordinatedResult:
        params = params or {}
        if capability in _SESSION_CAPABILITIES:
            return await self._run_session(capability, params)
        spec = CAPABILITIES.get(capability)
        if spec is None or capability not in self._agent.capabilities:
            request = ExecutionRequest(
                action=capability or "unknown_host_capability",
                blocked_reason=f"unknown host capability: {capability}",
            )
            async def _blocked() -> None:
                return None
            return await self._coordinator.execute(request, _blocked)

        risk = self._resolved_risk(capability, params, spec.risk)
        node = PlanNode(id=capability, capability=capability, params=params)
        request = ExecutionRequest(
            action=capability,
            target="",
            target_required=False,
            risk=risk,
            params=params,
            executor="internal",
            dependency=capability,
            dependency_available=True,
            metadata={"source": "host_controller", "capability": capability},
        )
        context = {"filesystem_scope": self._scope, "command_policy": self._policy, "stdin": stdin}

        async def _op() -> Any:
            return await self._agent.run(node, self._registry, context=context)

        return await self._coordinator.execute(request, _op)

    async def _run_session(self, capability: str, params: dict[str, Any]) -> CoordinatedResult:
        """Persistent-session lifecycle (subsystem 12), governed through the coordinator.

        The session object lives on this controller, so cwd/env persist across
        turns; ``session_exec`` classifies each command before the gate exactly like
        ``shell_command``, so risk, approval, audit, and evidence are unchanged.
        """
        if capability == "session_open":
            cwd = (params.get("cwd") or "").strip() or None
            request = ExecutionRequest(
                action="session_open", risk=RiskLevel.READ, executor="internal",
                params={"cwd": cwd or ""}, metadata={"source": "host_controller", "capability": capability},
            )

            async def _open() -> Any:
                if self._policy is None:
                    return self._agent._result("session_open", {"ok": False, "error": "no command policy in scope; session denied"})
                self._session = HostSession(self._policy, scope=self._scope, cwd=cwd)
                return self._agent._result("session_open", {"ok": True, "cwd": self._session.cwd})

            return await self._coordinator.execute(request, _open)

        if capability == "session_close":
            request = ExecutionRequest(
                action="session_close", risk=RiskLevel.READ, executor="internal",
                metadata={"source": "host_controller", "capability": capability},
            )

            async def _close() -> Any:
                summary = self._session.summary() if self._session is not None else {"cwd": "", "commands_run": 0}
                self._session = None
                return self._agent._result(
                    "session_close",
                    {"ok": True, "cwd": summary.get("cwd", ""), "commands_run": summary.get("commands_run", 0)},
                )

            return await self._coordinator.execute(request, _close)

        # session_exec: one command, per-command risk-classified, in the persistent session.
        argv = HostAgent._resolve_argv(params)
        if not argv:
            request = ExecutionRequest(action="session_exec", executor="internal",
                                       blocked_reason="empty command")

            async def _blocked() -> None:
                return None

            return await self._coordinator.execute(request, _blocked)

        risk = self._resolved_risk("session_exec", {"argv": argv}, RiskLevel.WRITE)
        request = ExecutionRequest(
            action="session_exec", risk=risk, executor="internal", params={"argv": argv},
            metadata={"source": "host_controller", "capability": "session_exec"},
        )

        async def _exec() -> Any:
            if self._policy is None:
                return self._agent._result("session_exec", {"ok": False, "error": "no command policy in scope; session denied"})
            if self._session is None:
                self._session = HostSession(self._policy, scope=self._scope)
            return self._agent._result("session_exec", self._session.run(argv))

        return await self._coordinator.execute(request, _exec)
