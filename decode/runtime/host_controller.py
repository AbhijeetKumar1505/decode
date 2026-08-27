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
from ..hostcontrol import CommandPolicy, FilesystemScope
from ..hostcontrol.policy import RiskLevel as _HostRisk
from ..planner.dag import PlanNode
from ..skills.base import RiskLevel
from .coordinator import CoordinatedResult, ExecutionCoordinator, ExecutionRequest

_RISK_ORDER = {RiskLevel.READ: 0, RiskLevel.WRITE: 1, RiskLevel.DESTRUCTIVE: 2}


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

    def set_scope(self, filesystem_scope: FilesystemScope, command_policy: CommandPolicy | None) -> None:
        self._scope = filesystem_scope
        self._policy = command_policy

    def _resolved_risk(self, capability: str, params: dict, baseline: RiskLevel) -> RiskLevel:
        if self._policy is None:
            return baseline
        if capability == "shell_command":
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
