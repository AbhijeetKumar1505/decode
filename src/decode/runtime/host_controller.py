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
from ..execution import ExecutionProvider, ExecutionResult
from ..hostcontrol import (
    CommandPolicy,
    FilesystemScope,
    HostSession,
    ScopeViolation,
    command_output_paths,
    command_requires_target,
    command_target,
)
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
        executor: ExecutionProvider | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._registry = _InternalSpecRegistry()
        self._agent = HostAgent()
        self._scope = filesystem_scope or FilesystemScope()
        self._policy = command_policy
        self._executor = executor
        # Persistent governed session (subsystem 12): a single HostSession whose
        # cwd/env persist across loop turns. Argv-governed — each command is
        # policy-classified and routed through the coordinator like shell_command.
        self._session: HostSession | None = None

    def set_scope(
        self, filesystem_scope: FilesystemScope, command_policy: CommandPolicy | None
    ) -> None:
        self._scope = filesystem_scope
        self._policy = command_policy

    def _resolved_risk(
        self, capability: str, params: dict, baseline: RiskLevel
    ) -> RiskLevel:
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
                if (
                    argv
                    and _RISK_ORDER[self._policy.classify(argv)] > _RISK_ORDER[worst]
                ):
                    worst = self._policy.classify(argv)
            return worst
        return baseline

    async def run(
        self,
        capability: str,
        params: dict[str, Any] | None = None,
        *,
        stdin: str | None = None,
    ) -> CoordinatedResult:
        params = params or {}
        if capability in _SESSION_CAPABILITIES:
            spec = CAPABILITIES[capability]
            try:
                normalized_session_params = spec.normalize_params(params)
            except ValueError as exc:
                return await self._blocked(
                    capability,
                    f"invalid parameters: {exc}",
                )
            if self._uses_external_provider:
                return await self._blocked(
                    capability,
                    "stateful host sessions are unavailable for the selected "
                    f"provider ({self._executor_name}); no local fallback was used",
                )
            return await self._run_session(capability, normalized_session_params)
        spec = CAPABILITIES.get(capability)
        if spec is None or capability not in self._agent.capabilities:
            request = ExecutionRequest(
                action=capability or "unknown_host_capability",
                blocked_reason=f"unknown host capability: {capability}",
            )

            async def _blocked() -> None:
                return None

            return await self._coordinator.execute(request, _blocked)

        try:
            normalized_params = spec.normalize_params(params)
        except ValueError as exc:
            request = ExecutionRequest(
                action=capability,
                risk=spec.risk,
                params={},
                executor="internal",
                blocked_reason=f"invalid parameters: {exc}",
                metadata={"source": "host_controller", "capability": capability},
            )

            async def _invalid() -> None:
                return None

            return await self._coordinator.execute(request, _invalid)

        approval_params = dict(normalized_params)
        resolved_target = ""
        target_required = False
        if capability == "host_session":
            import json

            try:
                steps = json.loads(normalized_params["commands"])
            except (json.JSONDecodeError, TypeError):
                return await self._blocked(
                    capability,
                    "commands must be a JSON list of argument vectors",
                )
            if not isinstance(steps, list):
                return await self._blocked(
                    capability,
                    "commands must be a JSON list of argument vectors",
                )
            outputs: list[str] = []
            for step in steps:
                argv = step if isinstance(step, list) else shlex.split(str(step))
                try:
                    if self._policy is None:
                        raise ScopeViolation(
                            "no command policy in scope; session denied"
                        )
                    self._policy.check(argv)
                    if command_requires_target(argv):
                        raise ScopeViolation(
                            "network commands are unavailable in host_session; "
                            "use shell_command with an explicit target"
                        )
                    for output in command_output_paths(argv):
                        self._scope.check(output, write=True)
                        outputs.append(str(output))
                except (ScopeViolation, ValueError) as exc:
                    return await self._blocked(capability, str(exc))
            if outputs:
                approval_params["_resolved_outputs"] = sorted(set(outputs))
        if capability == "shell_command":
            if self._policy is None:
                request = ExecutionRequest(
                    action=capability,
                    risk=spec.risk,
                    params=approval_params,
                    executor="internal",
                    blocked_reason="no command policy in scope; shell command denied",
                )

                async def _no_policy() -> None:
                    return None

                return await self._coordinator.execute(request, _no_policy)
            argv = HostAgent._resolve_argv(normalized_params)
            resolved_target = str(normalized_params.get("target", "")) or command_target(
                argv
            )
            target_required = command_requires_target(argv)
            try:
                self._policy.check(argv)
                outputs = command_output_paths(argv)
                if outputs and self._uses_external_provider:
                    raise ScopeViolation(
                        "output-producing commands are denied for external providers "
                        "until provider filesystem scope is configured"
                    )
                for output in outputs:
                    self._scope.check(output, write=True)
            except (ScopeViolation, ValueError) as exc:
                request = ExecutionRequest(
                    action=capability,
                    risk=self._resolved_risk(capability, normalized_params, spec.risk),
                    params=approval_params,
                    command=argv,
                    executor=self._executor_name,
                    blocked_reason=str(exc),
                    metadata={
                        "source": "host_controller",
                        "capability": capability,
                    },
                )

                async def _unsafe_command() -> None:
                    return None

                return await self._coordinator.execute(request, _unsafe_command)
            if outputs:
                approval_params["_resolved_outputs"] = [str(path) for path in outputs]

        risk = self._resolved_risk(capability, normalized_params, spec.risk)
        node = PlanNode(
            id=capability,
            capability=capability,
            params=normalized_params,
        )
        request = ExecutionRequest(
            action=capability,
            target=resolved_target,
            target_required=target_required,
            risk=risk,
            params=approval_params,
            command=(
                HostAgent._resolve_argv(normalized_params)
                if capability == "shell_command"
                else self._provider_discovery_command(normalized_params)
                if capability == "list_tools" and self._uses_external_provider
                else ""
            ),
            executor=self._executor_name_for(capability),
            dependency=capability,
            dependency_available=True,
            metadata={"source": "host_controller", "capability": capability},
        )
        context = {
            "filesystem_scope": self._scope,
            "command_policy": self._policy,
            "stdin": stdin,
        }

        async def _op() -> Any:
            if capability == "shell_command" and self._uses_external_provider:
                if stdin is not None:
                    return ExecutionResult(
                        command=HostAgent._resolve_argv(normalized_params),
                        provider=self._executor_name,
                        success=False,
                        exit_code=-1,
                        error=(
                            "stdin forwarding is unavailable for the selected "
                            "external provider"
                        ),
                    )
                return await self._executor.execute(
                    HostAgent._resolve_argv(normalized_params)
                )
            if capability == "list_tools" and self._uses_external_provider:
                return await self._list_provider_tools(normalized_params)
            return await self._agent.run(node, self._registry, context=context)

        return await self._coordinator.execute(request, _op)

    @property
    def _executor_name(self) -> str:
        return self._executor.name if self._executor is not None else "internal"

    @property
    def _uses_external_provider(self) -> bool:
        return self._executor is not None and self._executor.name != "local"

    def _executor_name_for(self, capability: str) -> str:
        if capability in {"list_tools", "shell_command"}:
            return self._executor_name
        return "internal"

    async def _blocked(self, capability: str, reason: str) -> CoordinatedResult:
        request = ExecutionRequest(
            action=capability,
            executor=self._executor_name,
            blocked_reason=reason,
            metadata={"source": "host_controller", "capability": capability},
        )

        async def _operation() -> None:
            return None

        return await self._coordinator.execute(request, _operation)

    async def _list_provider_tools(self, params: dict[str, Any]) -> Any:
        query = str(params.get("query", "")).lower()
        limit = int(params.get("limit", 400))
        environment = await self._executor.execute(["/usr/bin/env"])
        if not environment.success:
            return environment
        path_value = next(
            (
                line.removeprefix("PATH=")
                for line in environment.stdout.splitlines()
                if line.startswith("PATH=")
            ),
            "",
        )
        path_dirs = [item for item in path_value.split(":") if item]
        if not path_dirs:
            return ExecutionResult(
                command=self._provider_discovery_command(params),
                provider=self._executor_name,
                success=False,
                exit_code=-1,
                error="selected provider returned no PATH for tool discovery",
            )
        result = await self._executor.execute(
            [
                "/usr/bin/find",
                *path_dirs,
                "-maxdepth",
                "1",
                "-executable",
                "-printf",
                "%y\t%f\t%p\\n",
            ]
        )
        if not result.success and not result.stdout:
            return result
        tools: dict[str, str] = {}
        for line in result.stdout.splitlines():
            fields = line.split("\t", 2)
            if len(fields) != 3 or fields[0] not in {"f", "l"}:
                continue
            if query and query not in fields[1].lower():
                continue
            tools.setdefault(fields[1], fields[2])
        ordered = [
            {"name": name, "path": path}
            for name, path in sorted(tools.items())[:limit]
        ]
        return self._agent._result(
            "list_tools",
            {
                "ok": True,
                "tools": ordered,
                "count": len(ordered),
                "truncated": len(tools) > limit,
                "path_dirs": path_dirs,
                "provider": self._executor_name,
                "warnings": [result.stderr[:500]]
                if not result.success and result.stderr
                else [],
            },
        )

    @staticmethod
    def _provider_discovery_command(params: dict[str, Any]) -> list[str]:
        return [
            "provider-discovery",
            str(params.get("query", "")),
            str(int(params.get("limit", 400))),
        ]

    async def _run_session(
        self, capability: str, params: dict[str, Any]
    ) -> CoordinatedResult:
        """Persistent-session lifecycle (subsystem 12), governed through the coordinator.

        The session object lives on this controller, so cwd/env persist across
        turns; ``session_exec`` classifies each command before the gate exactly like
        ``shell_command``, so risk, approval, audit, and evidence are unchanged.
        """
        if capability == "session_open":
            cwd = (params.get("cwd") or "").strip() or None
            if cwd is not None and not self._scope.allows(cwd, write=False):
                return await self._blocked(
                    capability,
                    f"path '{cwd}' is outside the authorized read scope",
                )
            request = ExecutionRequest(
                action="session_open",
                risk=RiskLevel.READ,
                executor="internal",
                params={"cwd": cwd or ""},
                metadata={"source": "host_controller", "capability": capability},
            )

            async def _open() -> Any:
                if self._policy is None:
                    return self._agent._result(
                        "session_open",
                        {
                            "ok": False,
                            "error": "no command policy in scope; session denied",
                        },
                    )
                self._session = HostSession(self._policy, scope=self._scope, cwd=cwd)
                return self._agent._result(
                    "session_open", {"ok": True, "cwd": self._session.cwd}
                )

            return await self._coordinator.execute(request, _open)

        if capability == "session_close":
            request = ExecutionRequest(
                action="session_close",
                risk=RiskLevel.READ,
                executor="internal",
                metadata={"source": "host_controller", "capability": capability},
            )

            async def _close() -> Any:
                summary = (
                    self._session.summary()
                    if self._session is not None
                    else {"cwd": "", "commands_run": 0}
                )
                self._session = None
                return self._agent._result(
                    "session_close",
                    {
                        "ok": True,
                        "cwd": summary.get("cwd", ""),
                        "commands_run": summary.get("commands_run", 0),
                    },
                )

            return await self._coordinator.execute(request, _close)

        # session_exec: one command, per-command risk-classified, in the persistent session.
        argv = HostAgent._resolve_argv(params)
        if not argv:
            request = ExecutionRequest(
                action="session_exec",
                executor="internal",
                blocked_reason="empty command",
            )

            async def _blocked() -> None:
                return None

            return await self._coordinator.execute(request, _blocked)

        if self._policy is None:
            return await self._blocked(
                capability,
                "no command policy in scope; session denied",
            )
        try:
            self._policy.check(argv)
            if command_requires_target(argv):
                raise ScopeViolation(
                    "network commands are unavailable in session_exec; "
                    "use shell_command with an explicit target"
                )
            outputs = command_output_paths(
                argv,
                cwd=self._session.cwd if self._session is not None else None,
            )
            for output in outputs:
                self._scope.check(output, write=True)
        except (ScopeViolation, ValueError) as exc:
            return await self._blocked(capability, str(exc))

        risk = self._resolved_risk("session_exec", {"argv": argv}, RiskLevel.WRITE)
        approval_params: dict[str, Any] = {"argv": argv}
        if outputs:
            approval_params["_resolved_outputs"] = [str(path) for path in outputs]
        request = ExecutionRequest(
            action="session_exec",
            risk=risk,
            executor="internal",
            params=approval_params,
            command=argv,
            metadata={"source": "host_controller", "capability": "session_exec"},
        )

        async def _exec() -> Any:
            if self._policy is None:
                return self._agent._result(
                    "session_exec",
                    {
                        "ok": False,
                        "error": "no command policy in scope; session denied",
                    },
                )
            if self._session is None:
                self._session = HostSession(self._policy, scope=self._scope)
            return self._agent._result("session_exec", self._session.run(argv))

        return await self._coordinator.execute(request, _exec)
