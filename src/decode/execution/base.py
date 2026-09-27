import re
import shlex
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextvars import ContextVar
from enum import Enum
from functools import wraps
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Command = str | Sequence[str]
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_absolute_provider_path(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


class FilesystemMode(str, Enum):
    SHARED = "shared"
    MAPPED = "mapped"
    REMOTE = "remote"
    NONE = "none"


class ProviderPathStyle(str, Enum):
    POSIX = "posix"
    WINDOWS = "windows"


class EnvironmentCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_execution: bool = False
    tool_discovery: bool = False
    cwd: bool = False
    environment: bool = False
    path_mapping: bool = False
    scoped_filesystem: bool = False
    stateful_sessions: bool = False


class ProviderPathMapping(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host_root: str
    provider_root: str
    writable: bool = False
    provider_style: ProviderPathStyle = ProviderPathStyle.POSIX

    @field_validator("host_root", "provider_root")
    @classmethod
    def require_nonempty_root(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("path mapping roots cannot be empty")
        return normalized

    @model_validator(mode="after")
    def require_absolute_roots(self) -> "ProviderPathMapping":
        if not Path(self.host_root).expanduser().is_absolute():
            raise ValueError("host_root must be absolute")
        provider_root = (
            PureWindowsPath(self.provider_root)
            if self.provider_style == ProviderPathStyle.WINDOWS
            else PurePosixPath(self.provider_root)
        )
        if not provider_root.is_absolute():
            raise ValueError("provider_root must be absolute")
        return self


class ResolvedProviderPath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host_path: str
    provider_path: str
    writable: bool
    mapping: ProviderPathMapping | None = None


class EnvironmentIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0.0"
    name: str
    kind: str
    qualifier: str = ""
    platform: str = "unknown"
    filesystem_mode: FilesystemMode = FilesystemMode.NONE
    capabilities: EnvironmentCapabilities = Field(
        default_factory=EnvironmentCapabilities
    )
    path_mappings: tuple[ProviderPathMapping, ...] = ()


class ExecutionContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cwd: str = ""
    environment: dict[str, str] = Field(default_factory=dict)
    declared_outputs: tuple[str, ...] = ()

    @field_validator("cwd")
    @classmethod
    def reject_nul_cwd(cls, value: str) -> str:
        normalized = str(value).strip()
        if "\x00" in normalized:
            raise ValueError("cwd cannot contain NUL")
        if normalized and not _is_absolute_provider_path(normalized):
            raise ValueError("cwd must be an absolute provider path")
        return normalized

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_name, raw_value in value.items():
            name = str(raw_name)
            item = str(raw_value)
            if not _ENVIRONMENT_NAME.fullmatch(name):
                raise ValueError(f"invalid environment variable name: {name}")
            if "\x00" in item:
                raise ValueError(f"environment variable {name} contains NUL")
            normalized[name] = item
        return normalized

    @field_validator("declared_outputs")
    @classmethod
    def validate_declared_outputs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        outputs: list[str] = []
        for raw in value:
            output = str(raw).strip()
            if not output or "\x00" in output:
                raise ValueError("declared output paths must be non-empty and NUL-free")
            if not _is_absolute_provider_path(output):
                raise ValueError("declared output paths must be absolute")
            if output not in outputs:
                outputs.append(output)
        return tuple(outputs)

    @property
    def is_empty(self) -> bool:
        return not self.cwd and not self.environment and not self.declared_outputs


def command_display(command: Command) -> str:
    if isinstance(command, str):
        return command
    return shlex.join(str(part) for part in command)


_ACTIVE_EXECUTION_CONTEXT: ContextVar[tuple[str, str, str] | None] = ContextVar(
    "decode_active_execution_context",
    default=None,
)


def _activate_execution(action: str, executor: str = "", target: str = "") -> Any:
    return _ACTIVE_EXECUTION_CONTEXT.set((action, executor, target))


def _reset_execution(token: Any) -> None:
    _ACTIVE_EXECUTION_CONTEXT.reset(token)


def _execution_matches(action: str) -> bool:
    context = _ACTIVE_EXECUTION_CONTEXT.get()
    return context is not None and context[0] == action


def _provider_execution_matches(provider: str) -> bool:
    context = _ACTIVE_EXECUTION_CONTEXT.get()
    if context is None or not context[1] or context[1] == "internal":
        return False
    expected_kind = context[1].split("/", 1)[0].lower()
    provider_kind = provider.split("/", 1)[0].lower()
    return expected_kind == provider_kind


def require_governed_external_io(
    *,
    action: str = "",
    provider: str = "local",
    target: str = "",
) -> None:
    context = _ACTIVE_EXECUTION_CONTEXT.get()
    if context is None or not _provider_execution_matches(provider):
        raise RuntimeError(
            "Direct external I/O is disabled; use ExecutionCoordinator with "
            f"the {provider} executor"
        )
    if action and context[0] != action:
        raise RuntimeError(
            "External I/O action does not match the coordinator-authorized action"
        )
    authorized_target = context[2].strip()
    requested_target = target.strip()
    if requested_target and authorized_target != requested_target:
        raise RuntimeError(
            "External I/O target does not match the coordinator-authorized target"
        )


class ExecutionResult(BaseModel):
    """Uniform result for a single command run through any ExecutionProvider.

    Supersedes the old sandbox.CommandResult: carries enough context
    (command, duration, timeout/error flags) for the agent, TUI, and audit
    layer while remaining backward-compatible with v2 skills that only read
    success/stdout/stderr/exit_code.
    """

    schema_version: str = "1.0.0"
    command: str = ""
    provider: str = ""
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration: float = 0.0
    timed_out: bool = False
    error: str | None = None
    normalized: dict[str, Any] = Field(default_factory=dict)
    partial: bool = False
    parser_warnings: list[str] = Field(default_factory=list)
    tool_version: str = ""
    adapter_id: str = ""
    adapter_version: str = ""
    parser_id: str = ""
    parser_version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("command", mode="before")
    @classmethod
    def normalize_command_display(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, Sequence):
            return command_display(value)
        return str(value or "")

    @property
    def summary(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        if self.timed_out:
            return f"Timed out after {self.duration:.1f}s. Partial output:\n{self.stdout[:500]}"
        if self.exit_code != 0:
            return f"Exit code {self.exit_code}.\nSTDOUT: {self.stdout[:500]}\nSTDERR: {self.stderr[:500]}"
        return self.stdout[:2000]


class ProviderSession(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str = Field(default="1.0.0", frozen=True)
    session_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        frozen=True,
        pattern=r"^[a-f0-9]{32}$",
    )
    provider: str = Field(min_length=1, frozen=True)
    context: ExecutionContext = Field(default_factory=ExecutionContext)
    command_limit: int = Field(default=512, ge=1, le=4096, frozen=True)
    commands_run: int = Field(default=0, ge=0)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    closed: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "cwd": self.context.cwd,
            "command_limit": self.command_limit,
            "commands_run": self.commands_run,
            "closed": self.closed,
            "transcript": list(self.transcript),
        }


class EnvironmentProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def platform(self) -> str:
        return "unknown"

    @property
    def command_timeout_seconds(self) -> int:
        return 60

    @property
    def filesystem_mode(self) -> FilesystemMode:
        return FilesystemMode.NONE

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities()

    @property
    def path_mappings(self) -> tuple[ProviderPathMapping, ...]:
        return ()

    def identify(self) -> EnvironmentIdentity:
        kind, separator, qualifier = self.name.partition("/")
        return EnvironmentIdentity(
            name=self.name,
            kind=kind,
            qualifier=qualifier if separator else "",
            platform=self.platform,
            filesystem_mode=self.filesystem_mode,
            capabilities=self.capabilities,
            path_mappings=self.path_mappings,
        )

    def prepare_context(
        self,
        context: ExecutionContext | None = None,
        *,
        env: dict[str, str] | None = None,
    ) -> ExecutionContext:
        if context is not None and env is not None:
            raise ValueError("use ExecutionContext.environment instead of env together")
        resolved = context or ExecutionContext(environment=env or {})
        unsupported: list[str] = []
        if resolved.cwd and not self.capabilities.cwd:
            unsupported.append("cwd")
        if resolved.environment and not self.capabilities.environment:
            unsupported.append("environment")
        if resolved.declared_outputs and not self.capabilities.path_mapping:
            unsupported.append("declared_outputs")
        if unsupported:
            raise ValueError(
                f"provider {self.name} does not support execution context fields: "
                + ", ".join(unsupported)
            )
        return resolved

    def open_session(
        self,
        context: ExecutionContext | None = None,
    ) -> ProviderSession:
        if not self.capabilities.stateful_sessions:
            raise ValueError(f"provider {self.name} does not support stateful sessions")
        return ProviderSession(
            provider=self.name,
            context=self.prepare_context(context),
        )

    def prepare_session_context(
        self,
        session: ProviderSession,
        context: ExecutionContext | None = None,
    ) -> ExecutionContext:
        if not self.capabilities.stateful_sessions:
            raise ValueError(f"provider {self.name} does not support stateful sessions")
        if session.provider != self.name:
            raise ValueError(
                f"session provider {session.provider} does not match {self.name}"
            )
        if session.closed:
            raise ValueError(f"provider session {session.session_id} is closed")
        return self.prepare_context(context or session.context)

    def update_session_context(
        self,
        session: ProviderSession,
        context: ExecutionContext,
    ) -> None:
        session.context = self.prepare_session_context(session, context)

    async def execute_session(
        self,
        session: ProviderSession,
        command: Command,
        *,
        timeout: int = 60,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        execution_context = self.prepare_session_context(session, context)
        if session.commands_run >= session.command_limit:
            raise ValueError(
                f"provider session {session.session_id} reached its command limit"
            )
        result = await self.execute(
            command,
            timeout=timeout,
            context=execution_context,
        )
        session.commands_run += 1
        session.transcript.append(
            {
                "command": command_display(command),
                "cwd": execution_context.cwd,
                "success": result.success,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "error": result.error or "",
            }
        )
        return result

    def close_session(self, session: ProviderSession) -> dict[str, Any]:
        self.prepare_session_context(session)
        session.closed = True
        return session.summary()

    def map_path(
        self, path: str | Path, *, write: bool = False
    ) -> ResolvedProviderPath:
        candidate = Path(path).expanduser().resolve(strict=False)
        if self.filesystem_mode == FilesystemMode.NONE:
            raise ValueError(f"provider {self.name} has no filesystem contract")
        if self.filesystem_mode == FilesystemMode.SHARED:
            return ResolvedProviderPath(
                host_path=str(candidate),
                provider_path=str(candidate),
                writable=True,
            )

        matches: list[tuple[int, Path, ProviderPathMapping]] = []
        for mapping in self.path_mappings:
            root = Path(mapping.host_root).expanduser().resolve(strict=False)
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            matches.append((len(root.parts), root, mapping))
        if not matches:
            raise ValueError(
                f"path '{candidate}' has no mapping for provider {self.name}"
            )

        _depth, root, mapping = max(matches, key=lambda item: item[0])
        if write and not mapping.writable:
            raise ValueError(
                f"path '{candidate}' is not writable through provider {self.name}"
            )
        relative = candidate.relative_to(root)
        provider_root = (
            PureWindowsPath(mapping.provider_root)
            if mapping.provider_style == ProviderPathStyle.WINDOWS
            else PurePosixPath(mapping.provider_root)
        )
        provider_path = provider_root.joinpath(*relative.parts)
        return ResolvedProviderPath(
            host_path=str(candidate),
            provider_path=str(provider_path),
            writable=mapping.writable,
            mapping=mapping,
        )


class ExecutionProvider(EnvironmentProvider):
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        execute_implementation = cls.__dict__.get("execute")
        if execute_implementation is not None:

            @wraps(execute_implementation)
            async def governed_execute(
                self: "ExecutionProvider",
                *args: Any,
                **execute_kwargs: Any,
            ) -> ExecutionResult:
                if not _provider_execution_matches(self.name):
                    raise RuntimeError(
                        "Direct provider execution is disabled; use "
                        "ExecutionCoordinator with the selected executor"
                    )
                return await execute_implementation(self, *args, **execute_kwargs)

            cls.execute = governed_execute

        health_implementation = cls.__dict__.get("check_health")
        if health_implementation is not None:

            @wraps(health_implementation)
            async def health_check(
                self: "ExecutionProvider",
                *args: Any,
                **health_kwargs: Any,
            ) -> bool:
                token = _activate_execution("provider_health", self.name)
                try:
                    return await health_implementation(self, *args, **health_kwargs)
                finally:
                    _reset_execution(token)

            cls.check_health = health_check

    @abstractmethod
    async def execute(
        self,
        command: Command,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass
