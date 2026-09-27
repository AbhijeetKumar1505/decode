"""Governed invocation path for host-control capabilities.

Runs a single host capability through the ExecutionCoordinator with the
filesystem/command policy threaded into the agent context. For ad-hoc commands
the per-command risk is classified *before* the gate, so a WRITE command needs
approval and a DESTRUCTIVE one hits the destructive control — the capability's
baseline risk never under-gates a specific command.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from ..agents.host import HostAgent
from ..capabilities import CAPABILITIES
from ..execution import (
    ExecutionContext,
    ExecutionProvider,
    ExecutionResult,
    ProviderSession,
)
from ..hostcontrol import (
    CommandPolicy,
    FilesystemScope,
    HostSession,
    ScopeViolation,
    command_output_bindings,
    command_output_paths,
    command_requires_target,
    command_target,
    rewrite_command_output_paths,
)
from ..hostcontrol import operations as host_ops
from ..hostcontrol.policy import RiskLevel as _HostRisk
from ..hostcontrol.policy import strip_sudo
from ..planner.dag import PlanNode
from ..skills.base import RiskLevel
from .coordinator import (
    ActionPath,
    CoordinatedResult,
    ExecutionCoordinator,
    ExecutionIdentity,
    ExecutionRequest,
    Idempotency,
    ResolvedAction,
    ResolvedExecutable,
    SideEffect,
)

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
        # Stateful sessions remain bound to the selected execution provider.
        self._session: HostSession | None = None
        self._provider_session: ProviderSession | None = None
        self._provider_session_host_cwd = ""

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
                if not self._executor.capabilities.stateful_sessions:
                    return await self._blocked(
                        capability,
                        f"provider {self._executor_name} does not support stateful "
                        "sessions; no local fallback was used",
                    )
                return await self._run_provider_session(
                    capability,
                    normalized_session_params,
                )
            return await self._run_local_session(
                capability,
                normalized_session_params,
            )
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
        provider_argv: list[str] | None = None
        resolved_argv: list[str] | None = None
        resolved_executables: tuple[ResolvedExecutable, ...] = ()
        execution_context = ExecutionContext()
        resolved_action: ResolvedAction | None = None
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
                for output in outputs:
                    self._scope.check(output, write=True)
                if outputs and self._uses_external_provider:
                    mapped_outputs = [
                        self._executor.map_path(output, write=True) for output in outputs
                    ]
                    replacements = {
                        item.host_path: item.provider_path for item in mapped_outputs
                    }
                    provider_argv = rewrite_command_output_paths(argv, replacements)
                    implicit_output = any(
                        binding.argument_index is None
                        for binding in command_output_bindings(argv)
                    )
                    mapped_cwd = ""
                    if implicit_output:
                        mapped_cwd = self._executor.map_path(
                            Path.cwd(), write=True
                        ).provider_path
                    execution_context = ExecutionContext(
                        cwd=mapped_cwd,
                        declared_outputs=tuple(
                            item.provider_path for item in mapped_outputs
                        ),
                    )
                    approval_params["_provider_outputs"] = [
                        item.provider_path for item in mapped_outputs
                    ]
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
            resolved_argv, resolved_executables, resolution_failure = (
                await self._resolve_executables(
                    capability,
                    argv,
                    target=resolved_target,
                    target_required=target_required,
                )
            )
            if resolution_failure is not None:
                return resolution_failure
            if provider_argv is not None:
                for executable in resolved_executables:
                    provider_argv[executable.argv_index] = executable.path
            elif self._uses_external_provider:
                provider_argv = list(resolved_argv)
            if outputs:
                approval_params["_resolved_outputs"] = [str(path) for path in outputs]
            command = provider_argv or resolved_argv
            if self._uses_external_provider:
                declared_outputs = [
                    ActionPath(host=item.host_path, provider=item.provider_path)
                    for item in mapped_outputs
                ] if outputs else []
            else:
                declared_outputs = [
                    ActionPath(host=str(path), provider=str(path))
                    for path in outputs
                ]
            resolved_action = self._resolved_command_action(
                capability,
                command,
                original_argv=argv,
                outputs=declared_outputs,
                cwd=execution_context.cwd,
                target=resolved_target,
                executables=resolved_executables,
            )

        risk = self._resolved_risk(capability, normalized_params, spec.risk)
        if (
            resolved_action is not None
            and risk == RiskLevel.READ
            and any(
                effect in {
                    SideEffect.UNKNOWN,
                    SideEffect.NETWORK,
                    SideEffect.SESSION_STATE,
                }
                for effect in resolved_action.side_effects
            )
        ):
            risk = RiskLevel.WRITE
        node_params = normalized_params
        if capability == "shell_command" and resolved_argv is not None:
            node_params = {**normalized_params, "argv": resolved_argv}
        node = PlanNode(
            id=capability,
            capability=capability,
            params=node_params,
        )
        request = ExecutionRequest(
            action=capability,
            target=resolved_target,
            target_required=target_required,
            risk=risk,
            params=approval_params,
            command=(
                provider_argv or resolved_argv or HostAgent._resolve_argv(normalized_params)
                if capability == "shell_command"
                else self._provider_discovery_command(normalized_params)
                if capability == "list_tools" and self._uses_external_provider
                else ""
            ),
            executor=self._executor_name_for(capability),
            execution_identity=self._command_identity(resolved_action, capability)
            if resolved_action
            else ExecutionIdentity(),
            resolved_action=resolved_action,
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
            if capability == "shell_command" and resolved_action is not None:
                identity_error = await self._recheck_executables(resolved_action)
                if identity_error is not None:
                    return identity_error
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
                command = provider_argv or resolved_argv or HostAgent._resolve_argv(
                    normalized_params
                )
                if execution_context.is_empty:
                    return await self._executor.execute(
                        command, timeout=resolved_action.timeout_seconds
                    )
                return await self._executor.execute(
                    command,
                    timeout=resolved_action.timeout_seconds,
                    context=execution_context,
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

    def _resolved_command_action(
        self,
        capability: str,
        argv: list[str],
        *,
        original_argv: list[str],
        outputs: list[ActionPath] | None = None,
        cwd: str = "",
        target: str = "",
        session_state: bool = False,
        executables: tuple[ResolvedExecutable, ...] = (),
    ) -> ResolvedAction:
        effects: list[SideEffect] = []
        if outputs:
            effects.append(SideEffect.FILESYSTEM_WRITE)
        if command_requires_target(original_argv):
            effects.append(SideEffect.NETWORK)
        if session_state:
            effects.append(SideEffect.SESSION_STATE)
        return ResolvedAction(
            capability=capability,
            provider=self._executor_name_for(capability)
            if capability == "shell_command"
            else self._executor_name,
            tool=Path(argv[0]).name,
            target=target,
            argv=tuple(argv),
            executables=executables,
            cwd=cwd,
            outputs=tuple(outputs or ()),
            side_effects=tuple(effects) if effects else (SideEffect.UNKNOWN,),
            timeout_seconds=self._executor.command_timeout_seconds
            if self._uses_external_provider
            else 60,
            idempotency=Idempotency.IDEMPOTENT
            if session_state
            else Idempotency.UNKNOWN,
        )

    def _command_identity(
        self, action: ResolvedAction, capability: str
    ) -> ExecutionIdentity:
        spec = CAPABILITIES[capability]
        primary = action.executables[0] if action.executables else None
        return ExecutionIdentity(
            tool=action.tool,
            tool_version=action.tool_version,
            executable_path=primary.path if primary else "",
            executable_sha256=primary.sha256 if primary else "",
            capability_schema_version=spec.schema_version,
            arguments_schema_version=spec.arguments_schema_version,
            result_schema_version=spec.result_schema_version,
            parser_schema_version=spec.parser_schema_version,
            platform=self._executor.platform
            if self._uses_external_provider
            else sys.platform,
        )

    @staticmethod
    def _executable_indexes(argv: list[str]) -> list[int]:
        indexes = [0]
        is_sudo, inner = strip_sudo(argv)
        if is_sudo and inner:
            inner_index = len(argv) - len(inner)
            if inner_index not in indexes:
                indexes.append(inner_index)
        return indexes

    async def _inspect_provider_executable(self, executable: str) -> Any:
        if PurePosixPath(executable).is_absolute():
            if "\x00" in executable:
                return ExecutionResult(
                    provider=self._executor_name,
                    success=False,
                    exit_code=-1,
                    error="executable path contains NUL",
                )
            executable_test = await self._executor.execute(
                ["/usr/bin/test", "-x", executable]
            )
            if not executable_test.success:
                return self._agent._result(
                    "resolve_executable",
                    {"ok": True, "found": False, "requested": executable},
                )
            digest_result = await self._executor.execute(
                ["/usr/bin/sha256sum", executable]
            )
            digest = digest_result.stdout.split(" ", 1)[0]
            if not digest_result.success or not re.fullmatch(r"[a-f0-9]{64}", digest):
                return ExecutionResult(
                    provider=self._executor_name,
                    success=False,
                    exit_code=-1,
                    error="selected provider could not fingerprint the executable",
                )
            return self._agent._result(
                "resolve_executable",
                {
                    "ok": True,
                    "found": True,
                    "name": PurePosixPath(executable).name,
                    "path": executable,
                    "sha256": digest,
                },
            )
        inspected = await self._list_provider_tools(
            {"exact": executable, "query": "", "limit": 1}
        )
        if not inspected.success:
            return inspected
        tools = inspected.normalized.get("tools", [])
        if not tools:
            return self._agent._result(
                "resolve_executable",
                {"ok": True, "found": False, "requested": executable},
            )
        return self._agent._result(
            "resolve_executable",
            {"ok": True, "found": True, **tools[0]},
        )

    async def _resolve_executables(
        self,
        capability: str,
        argv: list[str],
        *,
        target: str = "",
        target_required: bool = False,
        environment: dict[str, str] | None = None,
    ) -> tuple[list[str], tuple[ResolvedExecutable, ...], CoordinatedResult | None]:
        indexes = self._executable_indexes(argv)
        requested = [argv[index] for index in indexes]
        request = ExecutionRequest(
            action="resolve_executable",
            target=target,
            target_required=target_required,
            risk=RiskLevel.READ,
            executor=self._executor_name,
            params={"capability": capability, "executables": requested},
            command=["resolve-executable", *requested],
            metadata={
                "source": "host_controller",
                "capability": capability,
                "purpose": "executable_identity",
            },
        )

        async def _inspect() -> Any:
            identities: list[dict[str, Any]] = []
            for index, executable in zip(indexes, requested, strict=True):
                if self._uses_external_provider:
                    inspected = await self._inspect_provider_executable(executable)
                    if not inspected.success:
                        return inspected
                    data = inspected.normalized
                else:
                    data = host_ops.inspect_executable(
                        executable,
                        search_path=environment.get("PATH", "")
                        if environment is not None
                        else None,
                    )
                    if not data["ok"]:
                        return self._agent._result("resolve_executable", data)
                identities.append(
                    {"argv_index": index, "requested": executable, **data}
                )
            return self._agent._result(
                "resolve_executable",
                {"ok": True, "executables": identities},
            )

        inspected = await self._coordinator.execute(request, _inspect)
        if not inspected.success:
            return argv, (), inspected
        identity_data = inspected.value.normalized.get("executables", [])
        missing = next(
            (item for item in identity_data if not item.get("found")),
            None,
        )
        if missing is not None:
            dependency = str(missing.get("requested", "") or "executable")
            blocked_request = ExecutionRequest(
                action=capability,
                risk=self._resolved_risk(capability, {"argv": argv}, RiskLevel.WRITE),
                executor=self._executor_name,
                command=argv,
                dependency=dependency,
                dependency_available=False,
                dependency_guidance=(
                    f"Required dependency missing in provider {self._executor_name}: "
                    f"{dependency} (command not found). Installation was not attempted."
                ),
                metadata={"source": "host_controller", "capability": capability},
            )

            async def _missing() -> None:
                return None

            blocked = await self._coordinator.execute(blocked_request, _missing)
            return argv, (), blocked

        resolved_argv = list(argv)
        identities: list[ResolvedExecutable] = []
        for item in identity_data:
            index = int(item["argv_index"])
            path = str(item["path"])
            resolved_argv[index] = path
            identities.append(
                ResolvedExecutable(
                    argv_index=index,
                    path=path,
                    sha256=str(item["sha256"]),
                )
            )
        return resolved_argv, tuple(identities), None

    async def _recheck_executables(
        self,
        action: ResolvedAction,
    ) -> ExecutionResult | None:
        for executable in action.executables:
            if self._uses_external_provider:
                result = await self._executor.execute(
                    ["/usr/bin/sha256sum", executable.path]
                )
                digest = result.stdout.split(" ", 1)[0]
                matches = result.success and digest == executable.sha256
            else:
                identity = host_ops.inspect_executable(executable.path)
                matches = (
                    identity["ok"]
                    and identity.get("found", False)
                    and identity.get("path") == executable.path
                    and identity.get("sha256") == executable.sha256
                )
            if not matches:
                return ExecutionResult(
                    command=list(action.argv),
                    provider=action.provider,
                    success=False,
                    exit_code=-1,
                    error="executable_identity_changed",
                    stderr="Executable identity changed after approval; execution denied",
                )
        return None

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
        exact = str(params.get("exact", "") or "").strip()
        if exact and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+@-]{0,255}", exact):
            return ExecutionResult(
                provider=self._executor_name,
                success=False,
                exit_code=-1,
                error="exact tool name must be a basename",
            )
        limit = int(params.get("limit", 400))
        environment = await self._executor.execute(["/usr/bin/printenv", "PATH"])
        if not environment.success:
            return environment
        path_value = environment.stdout.strip()
        path_dirs = [item for item in path_value.split(":") if item]
        if (
            not path_value
            or "\x00" in path_value
            or "\n" in path_value
            or len(path_dirs) > 128
            or any(not PurePosixPath(item).is_absolute() for item in path_dirs)
        ):
            return ExecutionResult(
                command=self._provider_discovery_command(params),
                provider=self._executor_name,
                success=False,
                exit_code=-1,
                error="selected provider returned an invalid PATH for tool discovery",
            )
        if exact:
            ordered: list[dict[str, str]] = []
            for directory in path_dirs:
                candidate = str(PurePosixPath(directory) / exact)
                regular = await self._executor.execute(
                    ["/usr/bin/test", "-f", candidate]
                )
                if not regular.success:
                    continue
                executable = await self._executor.execute(
                    ["/usr/bin/test", "-x", candidate]
                )
                if not executable.success:
                    continue
                digest_result = await self._executor.execute(
                    ["/usr/bin/sha256sum", candidate]
                )
                digest = digest_result.stdout.split(" ", 1)[0]
                if not digest_result.success or not re.fullmatch(
                    r"[a-f0-9]{64}", digest
                ):
                    return ExecutionResult(
                        provider=self._executor_name,
                        success=False,
                        exit_code=-1,
                        error=(
                            "selected provider could not fingerprint the executable"
                        ),
                    )
                ordered.append(
                    {"name": exact, "path": candidate, "sha256": digest}
                )
                break
            return self._agent._result(
                "list_tools",
                {
                    "ok": True,
                    "tools": ordered,
                    "count": len(ordered),
                    "truncated": False,
                    "path_dirs": path_dirs,
                    "provider": self._executor_name,
                    "warnings": [],
                },
            )
        find_args = [
            "/usr/bin/find",
            *path_dirs,
            "-maxdepth",
            "1",
            "-executable",
            "-printf",
            "%y\t%f\t%p\\n",
        ]
        result = await self._executor.execute(find_args)
        if not result.success and len(path_dirs) > 1:
            available_dirs = []
            for directory in path_dirs:
                present = await self._executor.execute(
                    ["/usr/bin/test", "-d", directory]
                )
                if present.success:
                    available_dirs.append(directory)
            if available_dirs and len(available_dirs) < len(path_dirs):
                result = await self._executor.execute(
                    [find_args[0], *available_dirs, *find_args[len(path_dirs) + 1:]]
                )
        if not result.success:
            result.partial = bool(result.stdout)
            return result
        tools: dict[str, str] = {}
        for line in result.stdout.splitlines():
            fields = line.split("\t", 2)
            if len(fields) != 3 or fields[0] not in {"f", "l"}:
                continue
            if query and query not in fields[1].lower():
                continue
            if exact and fields[1] != exact:
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

    def _session_host_cwd(self, requested: str = "") -> str:
        if requested:
            candidate = Path(requested).expanduser().resolve(strict=False)
        else:
            current = Path.cwd().resolve(strict=False)
            if self._scope.allows(current, write=False):
                candidate = current
            else:
                roots = [*self._scope.read_roots, *self._scope.write_roots]
                if not roots:
                    raise ScopeViolation(
                        "no authorized filesystem root is available for the session"
                    )
                candidate = Path(roots[0]).resolve(strict=False)
        self._scope.check(candidate, write=False)
        return str(candidate)

    def _provider_session_result(
        self,
        capability: str,
        result: ExecutionResult,
        session: ProviderSession,
        host_cwd: str,
    ) -> Any:
        error = result.error or result.stderr
        if not result.success and not error:
            error = f"provider command exited with status {result.exit_code}"
        return self._agent._result(
            capability,
            {
                "ok": result.success,
                "error": error,
                "session_id": session.session_id,
                "provider": session.provider,
                "cwd": host_cwd,
                "provider_cwd": session.context.cwd,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
            },
        )

    async def _run_provider_session(
        self,
        capability: str,
        params: dict[str, Any],
    ) -> CoordinatedResult:
        if self._executor is None:
            return await self._blocked(capability, "execution provider is unavailable")
        if self._policy is None:
            return await self._blocked(
                capability,
                "no command policy in scope; session denied",
            )

        if capability == "session_open":
            if self._provider_session is not None:
                return await self._blocked(
                    capability,
                    "a provider session is already open; close it before opening another",
                )
            try:
                host_cwd = self._session_host_cwd(
                    str(params.get("cwd", "") or "").strip()
                )
                provider_cwd = self._executor.map_path(
                    host_cwd,
                    write=False,
                ).provider_path
                pending = self._executor.open_session(
                    ExecutionContext(cwd=provider_cwd)
                )
            except (ScopeViolation, ValueError) as exc:
                return await self._blocked(capability, str(exc))
            request = ExecutionRequest(
                action="session_open",
                risk=RiskLevel.READ,
                executor=self._executor_name,
                params={
                    "session_id": pending.session_id,
                    "provider": pending.provider,
                    "cwd": host_cwd,
                    "provider_cwd": provider_cwd,
                },
                metadata={"source": "host_controller", "capability": capability},
            )

            async def _open() -> Any:
                self._provider_session = pending
                self._provider_session_host_cwd = host_cwd
                return self._agent._result(
                    "session_open",
                    {
                        "ok": True,
                        "session_id": pending.session_id,
                        "provider": pending.provider,
                        "cwd": host_cwd,
                        "provider_cwd": provider_cwd,
                    },
                )

            return await self._coordinator.execute(request, _open)

        if capability == "session_close":
            session = self._provider_session
            request_params: dict[str, Any] = {"provider": self._executor_name}
            if session is not None:
                request_params.update(
                    {
                        "session_id": session.session_id,
                        "cwd": self._provider_session_host_cwd,
                        "provider_cwd": session.context.cwd,
                    }
                )
            request = ExecutionRequest(
                action="session_close",
                risk=RiskLevel.READ,
                executor=self._executor_name,
                params=request_params,
                metadata={"source": "host_controller", "capability": capability},
            )

            async def _close() -> Any:
                if session is None:
                    summary = {
                        "session_id": "",
                        "provider": self._executor_name,
                        "cwd": "",
                        "provider_cwd": "",
                        "commands_run": 0,
                    }
                else:
                    closed = self._executor.close_session(session)
                    summary = {
                        "session_id": session.session_id,
                        "provider": session.provider,
                        "cwd": self._provider_session_host_cwd,
                        "provider_cwd": closed.get("cwd", ""),
                        "commands_run": closed.get("commands_run", 0),
                    }
                self._provider_session = None
                self._provider_session_host_cwd = ""
                return self._agent._result(
                    "session_close",
                    {"ok": True, **summary},
                )

            return await self._coordinator.execute(request, _close)

        argv = HostAgent._resolve_argv(params)
        if not argv:
            return await self._blocked(capability, "empty command")
        try:
            self._policy.check(argv)
            if command_requires_target(argv):
                raise ScopeViolation(
                    "network commands are unavailable in session_exec; "
                    "use shell_command with an explicit target"
                )
            existing = self._provider_session
            if existing is None:
                host_cwd = self._session_host_cwd()
                provider_cwd = self._executor.map_path(
                    host_cwd,
                    write=False,
                ).provider_path
                session = self._executor.open_session(
                    ExecutionContext(cwd=provider_cwd)
                )
            else:
                host_cwd = self._provider_session_host_cwd
                session = existing
                self._scope.check(host_cwd, write=False)
                current_provider_cwd = self._executor.map_path(
                    host_cwd,
                    write=False,
                ).provider_path
                if current_provider_cwd != session.context.cwd:
                    raise ValueError(
                        "provider path mapping changed after the session was opened"
                    )
                self._executor.prepare_session_context(session)
            outputs = command_output_paths(argv, cwd=host_cwd)
            for output in outputs:
                self._scope.check(output, write=True)
            mapped_outputs = [
                self._executor.map_path(output, write=True) for output in outputs
            ]
        except (ScopeViolation, ValueError) as exc:
            return await self._blocked(capability, str(exc))

        approval_params: dict[str, Any] = {
            "argv": argv,
            "session_id": session.session_id,
            "provider": session.provider,
            "_host_cwd": host_cwd,
            "_provider_cwd": session.context.cwd,
        }
        provider_command = list(argv)
        execution_context = ExecutionContext(
            cwd=session.context.cwd,
            environment=dict(session.context.environment),
        )
        next_host_cwd = host_cwd
        next_context: ExecutionContext | None = None

        if Path(argv[0]).name == "cd":
            if len(argv) > 2:
                return await self._blocked(
                    capability,
                    "cd accepts at most one path argument",
                )
            try:
                target = Path(host_cwd) / (argv[1] if len(argv) == 2 else ".")
                next_host_cwd = str(target.expanduser().resolve(strict=False))
                self._scope.check(next_host_cwd, write=False)
                next_provider_cwd = self._executor.map_path(
                    next_host_cwd,
                    write=False,
                ).provider_path
                next_context = ExecutionContext(
                    cwd=next_provider_cwd,
                    environment=dict(session.context.environment),
                )
            except (ScopeViolation, ValueError) as exc:
                return await self._blocked(capability, str(exc))
            provider_command = ["/usr/bin/test", "-d", next_provider_cwd]
            approval_params["_next_host_cwd"] = next_host_cwd
            approval_params["_next_provider_cwd"] = next_provider_cwd
        elif mapped_outputs:
            replacements = {
                item.host_path: item.provider_path for item in mapped_outputs
            }
            provider_command = rewrite_command_output_paths(
                argv,
                replacements,
                cwd=host_cwd,
            )
            execution_context = ExecutionContext(
                cwd=session.context.cwd,
                environment=dict(session.context.environment),
                declared_outputs=tuple(
                    item.provider_path for item in mapped_outputs
                ),
            )
            approval_params["_resolved_outputs"] = [
                item.host_path for item in mapped_outputs
            ]
            approval_params["_provider_outputs"] = [
                item.provider_path for item in mapped_outputs
            ]

        provider_command, resolved_executables, resolution_failure = (
            await self._resolve_executables("session_exec", provider_command)
        )
        if resolution_failure is not None:
            return resolution_failure

        risk = self._resolved_risk("session_exec", {"argv": argv}, RiskLevel.WRITE)
        action = self._resolved_command_action(
            "session_exec",
            provider_command,
            original_argv=argv,
            outputs=[
                ActionPath(host=item.host_path, provider=item.provider_path)
                for item in mapped_outputs
            ],
            cwd=execution_context.cwd,
            session_state=next_context is not None,
            executables=resolved_executables,
        )
        if risk == RiskLevel.READ and (
            SideEffect.UNKNOWN in action.side_effects
            or SideEffect.SESSION_STATE in action.side_effects
        ):
            risk = RiskLevel.WRITE
        request = ExecutionRequest(
            action="session_exec",
            risk=risk,
            executor=self._executor_name,
            params=approval_params,
            command=provider_command,
            execution_identity=self._command_identity(action, "session_exec"),
            resolved_action=action,
            metadata={
                "source": "host_controller",
                "capability": "session_exec",
                "session_id": session.session_id,
            },
        )

        async def _exec() -> Any:
            identity_error = await self._recheck_executables(action)
            if identity_error is not None:
                return identity_error
            if existing is None:
                self._provider_session = session
                self._provider_session_host_cwd = host_cwd
            result = await self._executor.execute_session(
                session,
                provider_command,
                timeout=action.timeout_seconds,
                context=execution_context,
            )
            if result.success and next_context is not None:
                self._executor.update_session_context(session, next_context)
                self._provider_session_host_cwd = next_host_cwd
            return self._provider_session_result(
                "session_exec",
                result,
                session,
                self._provider_session_host_cwd,
            )

        return await self._coordinator.execute(request, _exec)

    async def _run_local_session(
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
        policy = self._policy
        session = self._session or HostSession(policy, scope=self._scope)
        cwd = session.cwd
        environment = dict(session.env)
        environment_sha256 = hashlib.sha256(
            json.dumps(environment, sort_keys=True).encode("utf-8")
        ).hexdigest()
        is_cd = argv[0] == "cd"
        try:
            if session._policy is not policy:
                raise ScopeViolation("session command policy changed; reopen the session")
            self._policy.check(argv)
            if command_requires_target(argv):
                raise ScopeViolation(
                    "network commands are unavailable in session_exec; "
                    "use shell_command with an explicit target"
                )
            self._scope.check(cwd, write=False)
            if is_cd and len(argv) > 2:
                raise ValueError("cd accepts at most one path")
            next_cwd = (
                str((Path(cwd) / (argv[1] if len(argv) > 1 else ".")).expanduser().resolve(strict=False))
                if is_cd
                else ""
            )
            if next_cwd:
                self._scope.check(next_cwd, write=False)
                if not Path(next_cwd).is_dir():
                    raise ValueError(f"not a directory: {next_cwd}")
            outputs = command_output_paths(argv, cwd=cwd)
            for output in outputs:
                self._scope.check(output, write=True)
        except (ScopeViolation, ValueError) as exc:
            return await self._blocked(capability, str(exc))

        resolved_argv, executables, blocked = (
            (argv, (), None)
            if is_cd
            else await self._resolve_executables(
                capability, argv, environment=environment
            )
        )
        if blocked is not None:
            return blocked
        action = self._resolved_command_action(
            capability,
            resolved_argv,
            original_argv=argv,
            outputs=[ActionPath(host=str(path), provider=str(path)) for path in outputs],
            cwd=cwd,
            session_state=is_cd,
            executables=executables,
        )
        risk = self._resolved_risk("session_exec", {"argv": argv}, RiskLevel.WRITE)
        if risk == RiskLevel.READ and (
            SideEffect.UNKNOWN in action.side_effects
            or SideEffect.SESSION_STATE in action.side_effects
        ):
            risk = RiskLevel.WRITE
        approval_params: dict[str, Any] = {
            "argv": argv,
            "_resolved_cwd": cwd,
            "_environment_sha256": environment_sha256,
        }
        if next_cwd:
            approval_params["_next_cwd"] = next_cwd
        if outputs:
            approval_params["_resolved_outputs"] = [str(path) for path in outputs]
        request = ExecutionRequest(
            action="session_exec",
            risk=risk,
            executor=self._executor_name,
            params=approval_params,
            command=resolved_argv,
            execution_identity=self._command_identity(action, capability),
            resolved_action=action,
            metadata={"source": "host_controller", "capability": "session_exec"},
        )

        async def _exec() -> Any:
            if (
                self._policy is not policy
                or session._policy is not policy
                or (self._session is not None and self._session is not session)
                or session.cwd != cwd
                or session.env != environment
                or (
                    next_cwd
                    and str(
                        (Path(cwd) / (argv[1] if len(argv) > 1 else "."))
                        .expanduser()
                        .resolve(strict=False)
                    )
                    != next_cwd
                )
            ):
                return ExecutionResult(
                    command=resolved_argv,
                    provider=self._executor_name,
                    success=False,
                    exit_code=-1,
                    error="session_context_changed",
                )
            try:
                self._policy.check(argv)
                self._scope.check(cwd, write=False)
                if next_cwd:
                    self._scope.check(next_cwd, write=False)
                for output in outputs:
                    self._scope.check(output, write=True)
            except (ScopeViolation, ValueError) as exc:
                return ExecutionResult(
                    command=resolved_argv,
                    provider=self._executor_name,
                    success=False,
                    exit_code=-1,
                    error=str(exc),
                )
            identity_error = await self._recheck_executables(action)
            if identity_error is not None:
                return identity_error
            self._session = session
            return self._agent._result("session_exec", session.run(resolved_argv))

        return await self._coordinator.execute(request, _exec)
