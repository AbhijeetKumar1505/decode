from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextvars import ContextVar
from functools import wraps
import shlex
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field, field_validator


Command = str | Sequence[str]


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
    error: Optional[str] = None
    normalized: Dict[str, Any] = Field(default_factory=dict)
    partial: bool = False
    parser_warnings: list[str] = Field(default_factory=list)
    tool_version: str = ""
    adapter_id: str = ""
    adapter_version: str = ""
    parser_id: str = ""
    parser_version: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

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


class ExecutionProvider(ABC):
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

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def execute(
        self, command: Command, timeout: int = 60, env: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass
