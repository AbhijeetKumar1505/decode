"""Governed execution coordination shared by migrated public execution flows."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..audit import AuditEvent, AuditLayer
from ..execution.base import _activate_execution, _reset_execution, command_display
from ..feedback import ExecutionFeedback, FeedbackStore
from ..governance import Decision, GovernanceGate
from ..logging_service import LoggingService
from ..persistence.evidence import (
    EvidenceReference,
    ProtectedEvidenceStore,
)
from ..skills.base import RiskLevel

if TYPE_CHECKING:
    from ..hostcontrol.hooks import HookRegistry

_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_SECRET_NAME_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|credential|password|secret|token)"
)


def redact_sensitive(value: Any, key: str = "") -> Any:
    if _SECRET_NAME_PATTERN.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_sensitive(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str):
        text = _SECRET_PATTERN.sub(r"\1=[REDACTED]", value)
        return _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    return value


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    BLOCKED = "blocked"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ExecutionErrorCategory(str, Enum):
    POLICY_DENIAL = "policy_denial"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_INVALID = "approval_invalid"
    APPROVAL_EXPIRED = "approval_expired"
    MISSING_DEPENDENCY = "missing_dependency"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    EXECUTION_FAILURE = "execution_failure"
    TELEMETRY_FAILURE = "telemetry_failure"
    UNSUPPORTED_ACTION = "unsupported_action"


class ExecutionIdentity(BaseModel):
    tool: str = Field(default="", max_length=128)
    tool_version: str = Field(default="", max_length=256)
    executable_path: str = Field(default="", max_length=4096)
    executable_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    adapter_id: str = Field(default="", max_length=128)
    adapter_version: str = Field(default="", max_length=64)
    parser_id: str = Field(default="", max_length=128)
    parser_version: str = Field(default="", max_length=64)
    capability_schema_version: str = Field(default="", max_length=64)
    arguments_schema_version: str = Field(default="", max_length=64)
    result_schema_version: str = Field(default="", max_length=64)
    parser_schema_version: str = Field(default="", max_length=64)
    platform: str = Field(default="", max_length=128)
    architecture: str = Field(default="", max_length=128)
    environment_version: str = Field(default="", max_length=512)

    @field_validator("executable_path")
    @classmethod
    def validate_executable_path(cls, value: str) -> str:
        if value and (
            "\x00" in value
            or not (
                PurePosixPath(value).is_absolute()
                or PureWindowsPath(value).is_absolute()
            )
        ):
            raise ValueError("execution identity executable path must be absolute")
        return value

    @model_validator(mode="after")
    def require_complete_executable_identity(self) -> ExecutionIdentity:
        if bool(self.executable_path) != bool(self.executable_sha256):
            raise ValueError("execution identity path and digest must be provided together")
        return self


class SideEffect(str, Enum):
    READ_ONLY = "read_only"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK = "network"
    SESSION_STATE = "session_state"
    UNKNOWN = "unknown"


class Idempotency(str, Enum):
    UNKNOWN = "unknown"
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


class EvidencePolicy(str, Enum):
    PROTECTED_RAW = "protected_raw"


class ParserPolicy(str, Enum):
    RAW_ONLY = "raw_only"


class ActionPath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(min_length=1)
    provider: str = Field(min_length=1)

    @field_validator("host", "provider")
    @classmethod
    def require_absolute_path(cls, value: str) -> str:
        if "\x00" in value or not (
            PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).is_absolute()
        ):
            raise ValueError("resolved action paths must be absolute and NUL-free")
        return value


class ResolvedExecutable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    argv_index: int = Field(ge=0, le=4095)
    path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("path")
    @classmethod
    def require_absolute_path(cls, value: str) -> str:
        if "\x00" in value or not (
            PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).is_absolute()
        ):
            raise ValueError("resolved executable path must be absolute and NUL-free")
        return value


class ResolvedAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0.0"
    capability: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    tool_version: str = ""
    target: str = ""
    argv: tuple[str, ...] = Field(min_length=1)
    executables: tuple[ResolvedExecutable, ...] = ()
    cwd: str = ""
    inputs: tuple[ActionPath, ...] = ()
    outputs: tuple[ActionPath, ...] = ()
    side_effects: tuple[SideEffect, ...] = Field(
        default=(SideEffect.UNKNOWN,),
        min_length=1,
    )
    timeout_seconds: int = Field(ge=1, le=3600)
    idempotency: Idempotency = Idempotency.UNKNOWN
    evidence_policy: EvidencePolicy = EvidencePolicy.PROTECTED_RAW
    parser_policy: ParserPolicy = ParserPolicy.RAW_ONLY

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or "\x00" in value for value in values):
            raise ValueError("resolved argv must contain non-empty NUL-free tokens")
        return values

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        if value and (
            "\x00" in value
            or not (
                PurePosixPath(value).is_absolute()
                or PureWindowsPath(value).is_absolute()
            )
        ):
            raise ValueError("resolved cwd must be absolute and NUL-free")
        return value

    @model_validator(mode="after")
    def validate_effects(self) -> ResolvedAction:
        if self.outputs and SideEffect.FILESYSTEM_WRITE not in self.side_effects:
            raise ValueError("declared outputs require filesystem_write side effect")
        indexes = [item.argv_index for item in self.executables]
        if len(indexes) != len(set(indexes)):
            raise ValueError("resolved executable argv indexes must be unique")
        if indexes and (indexes[0] != 0 or indexes != sorted(indexes)):
            raise ValueError("resolved executables must be ordered from argv index zero")
        for executable in self.executables:
            if executable.argv_index >= len(self.argv):
                raise ValueError("resolved executable argv index is out of range")
            if self.argv[executable.argv_index] != executable.path:
                raise ValueError("resolved executable path must match resolved argv")
        if self.executables:
            primary_path = self.executables[0].path
            primary_name = (
                PureWindowsPath(primary_path).name
                if PureWindowsPath(primary_path).is_absolute()
                else PurePosixPath(primary_path).name
            )
            if self.tool != primary_name:
                raise ValueError("resolved tool must match the primary executable path")
        return self

    def telemetry_summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capability": self.capability,
            "provider": self.provider,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "executable_count": len(self.executables),
            "executable_verified": bool(self.executables),
            "target_present": bool(self.target),
            "side_effects": [effect.value for effect in self.side_effects],
            "timeout_seconds": self.timeout_seconds,
            "idempotency": self.idempotency.value,
            "evidence_policy": self.evidence_policy.value,
            "parser_policy": self.parser_policy.value,
            "input_count": len(self.inputs),
            "output_count": len(self.outputs),
        }


class ExecutionRequest(BaseModel):
    action: str = Field(min_length=1)
    target: str = ""
    target_required: bool = False
    risk: RiskLevel = RiskLevel.WRITE
    params: dict[str, Any] = Field(default_factory=dict)
    command: str | list[str] = ""
    executor: str = ""
    required_privileges: list[str] = Field(default_factory=lambda: ["user"])
    credential_refs: list[str] = Field(default_factory=list)
    execution_identity: ExecutionIdentity = Field(default_factory=ExecutionIdentity)
    resolved_action: ResolvedAction | None = None
    approval_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    approval_expires_at: datetime | None = None
    dependency: str = ""
    dependency_available: bool = True
    dependency_guidance: str = ""
    blocked_reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("credential_refs")
    @classmethod
    def validate_credential_refs(cls, values: list[str]) -> list[str]:
        pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
        if any(not pattern.fullmatch(value) for value in values):
            raise ValueError("credential references must be opaque identifiers")
        return values

    @field_validator("required_privileges")
    @classmethod
    def validate_required_privileges(cls, values: list[str]) -> list[str]:
        allowed = {"user", "elevated", "root", "capability", "service_role"}
        if not values or any(value not in allowed for value in values):
            raise ValueError("required_privileges contains an unsupported value")
        return values

    @field_validator("approval_expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("approval_expires_at must be timezone-aware")
        return value

    def approval_digest(self) -> str:
        material = {
            "action": self.action,
            "target": self.target,
            "risk": self.risk.value,
            "params": self.params,
            "command": self.command,
            "executor": self.executor,
            "required_privileges": self.required_privileges,
            "credential_refs": self.credential_refs,
            "execution_identity": self.execution_identity.model_dump(),
            "resolved_action": self.resolved_action.model_dump(mode="json")
            if self.resolved_action
            else None,
            "approval_expires_at": self.approval_expires_at.isoformat()
            if self.approval_expires_at
            else "",
        }
        encoded = json.dumps(
            material, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def resolved_action_error(self) -> str:
        resolved = self.resolved_action
        if resolved is None:
            return ""
        if resolved.capability != self.action or resolved.provider != self.executor:
            return "resolved action does not match capability or provider"
        if resolved.target != self.target:
            return "resolved target does not match execution target"
        if list(resolved.argv) != self.command:
            return "resolved action argv does not match execution command"
        if self.execution_identity.tool != resolved.tool:
            return "resolved tool identity does not match execution identity"
        if self.execution_identity.tool_version != resolved.tool_version:
            return "resolved tool version does not match execution identity"
        if resolved.executables:
            primary = resolved.executables[0]
            if self.execution_identity.executable_path != primary.path:
                return "resolved executable path does not match execution identity"
            if self.execution_identity.executable_sha256 != primary.sha256:
                return "resolved executable digest does not match execution identity"
        if self.risk == RiskLevel.READ and any(
            effect != SideEffect.READ_ONLY for effect in resolved.side_effects
        ):
            return "resolved side effects require WRITE risk"
        return ""


class ApprovalRequest(BaseModel):
    request_id: str
    action: str
    target: str = ""
    risk: RiskLevel
    params: dict[str, Any] = Field(default_factory=dict)
    command: str = ""
    executor: str = ""
    required_privileges: list[str] = Field(default_factory=list)
    credential_refs: list[str] = Field(default_factory=list)
    execution_identity: ExecutionIdentity = Field(default_factory=ExecutionIdentity)
    resolved_action: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime
    digest: str

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("approval expiry must be timezone-aware")
        return value


class ApprovalGrant(BaseModel):
    digest: str
    approved_at: datetime
    expires_at: datetime

    @field_validator("approved_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("approval timestamps must be timezone-aware")
        return value


class CoordinatedResult(BaseModel):
    request_id: str
    action: str
    status: ExecutionStatus
    success: bool = False
    value: Any = None
    error_category: ExecutionErrorCategory | None = None
    error: str = ""
    duration: float = 0.0
    approval_digest: str = ""
    evidence: EvidenceReference | None = None


ApprovalCallback = Callable[
    [ApprovalRequest],
    bool | ApprovalGrant | Awaitable[bool | ApprovalGrant],
]
ExecutionOperation = Callable[[], Awaitable[Any]]


def target_from_params(params: dict[str, Any]) -> str:
    for key in (
        "target",
        "url",
        "domain",
        "host",
        "hostname",
        "ip",
        "address",
        "cidr",
        "network",
    ):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def credential_refs_from_params(params: dict[str, Any]) -> list[str]:
    return sorted(
        f"request-param:{key}"
        for key, value in params.items()
        if value not in (None, "", [], {}) and _SECRET_NAME_PATTERN.search(key)
    )


class ExecutionCoordinator:
    """Apply governance, bound approval, execution, and mandatory telemetry."""

    def __init__(
        self,
        gate: GovernanceGate,
        approval_callback: ApprovalCallback | None = None,
        logging_service: LoggingService | None = None,
        audit: AuditLayer | None = None,
        feedback: FeedbackStore | None = None,
        evidence_store: ProtectedEvidenceStore | None = None,
        hooks: HookRegistry | None = None,
    ) -> None:
        self._gate = gate
        self._approval_callback = approval_callback
        self._hooks = hooks
        self._audit = audit or gate.audit
        runtime_root = self._audit.base_path.parent
        self._logging = logging_service or LoggingService(runtime_root / "logs")
        self._feedback = feedback or FeedbackStore(runtime_root / "feedback")
        self._evidence = evidence_store or ProtectedEvidenceStore(
            runtime_root / "evidence" / "executions"
        )

    def set_approval_callback(self, callback: ApprovalCallback | None) -> None:
        self._approval_callback = callback

    def set_mode(self, mode: Any) -> None:
        self._gate.set_mode(mode)

    def get_mode(self) -> Any:
        return self._gate.mode

    async def execute(
        self,
        request: ExecutionRequest,
        operation: ExecutionOperation,
        approval_callback: ApprovalCallback | None = None,
    ) -> CoordinatedResult:
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        if request.risk != RiskLevel.READ and request.approval_expires_at is None:
            request.approval_expires_at = datetime.now(UTC) + timedelta(
                seconds=request.approval_ttl_seconds
            )
        digest = request.approval_digest()

        if request.blocked_reason:
            return self._finish_without_execution(
                request,
                request_id,
                digest,
                ExecutionStatus.BLOCKED,
                ExecutionErrorCategory.UNSUPPORTED_ACTION,
                request.blocked_reason,
                started,
            )

        if not request.dependency_available:
            error = request.dependency_guidance or (
                f"Required dependency missing: {request.dependency or request.action}"
            )
            return self._finish_without_execution(
                request,
                request_id,
                digest,
                ExecutionStatus.BLOCKED,
                ExecutionErrorCategory.MISSING_DEPENDENCY,
                error,
                started,
            )

        consistency_error = request.resolved_action_error()
        if consistency_error:
            return self._finish_without_execution(
                request,
                request_id,
                digest,
                ExecutionStatus.BLOCKED,
                ExecutionErrorCategory.UNSUPPORTED_ACTION,
                consistency_error,
                started,
            )

        if self._hooks is not None:
            from ..hostcontrol.hooks import HookEvent

            allow, hook_reason = self._hooks.run_pre(
                HookEvent(
                    phase="pre",
                    capability=request.action,
                    risk=request.risk,
                    target=request.target,
                    metadata=dict(request.metadata),
                )
            )
            if not allow:
                return self._finish_without_execution(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.BLOCKED,
                    ExecutionErrorCategory.UNSUPPORTED_ACTION,
                    hook_reason,
                    started,
                )

        try:
            decision = self._gate.evaluate(
                request.action,
                request.target,
                request.risk.value,
                target_required=request.target_required,
            )
        except Exception:
            return self._telemetry_unavailable(request, request_id, digest, started)

        if decision.decision == Decision.DENY:
            return self._finish_without_execution(
                request,
                request_id,
                digest,
                ExecutionStatus.DENIED,
                ExecutionErrorCategory.POLICY_DENIAL,
                decision.reason,
                started,
                audit_event=False,
            )

        if decision.decision == Decision.NEEDS_APPROVAL:
            selected_approval = approval_callback or self._approval_callback
            if selected_approval is None:
                return self._finish_without_execution(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.DENIED,
                    ExecutionErrorCategory.APPROVAL_REQUIRED,
                    "human approval is required",
                    started,
                )
            expires_at = request.approval_expires_at
            if expires_at is None or expires_at <= datetime.now(UTC):
                return self._finish_without_execution(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.DENIED,
                    ExecutionErrorCategory.APPROVAL_EXPIRED,
                    "approval request expired before execution",
                    started,
                )
            approval = ApprovalRequest(
                request_id=request_id,
                action=request.action,
                target=self._redact_text(request.target),
                risk=request.risk,
                params=self._safe_value(request.params),
                command=self._redact_text(command_display(request.command)),
                executor=request.executor,
                required_privileges=request.required_privileges,
                credential_refs=request.credential_refs,
                execution_identity=request.execution_identity,
                resolved_action=self._safe_value(
                    request.resolved_action.model_dump(mode="json")
                )
                if request.resolved_action
                else {},
                expires_at=expires_at,
                digest=digest,
            )
            try:
                grant = selected_approval(approval)
                if inspect.isawaitable(grant):
                    grant = await grant
            except Exception:
                grant = False
            if grant is True:
                now = datetime.now(UTC)
                grant = ApprovalGrant(
                    digest=digest,
                    approved_at=now,
                    expires_at=expires_at,
                )
            if grant is False:
                return self._finish_without_execution(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.DENIED,
                    ExecutionErrorCategory.APPROVAL_REJECTED,
                    "human approval was rejected",
                    started,
                )
            if not isinstance(grant, ApprovalGrant) or grant.digest != digest:
                return self._finish_without_execution(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.DENIED,
                    ExecutionErrorCategory.APPROVAL_INVALID,
                    "approval does not match the material execution request",
                    started,
                )
            now = datetime.now(UTC)
            if grant.approved_at > now or min(grant.expires_at, expires_at) <= now:
                return self._finish_without_execution(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.DENIED,
                    ExecutionErrorCategory.APPROVAL_EXPIRED,
                    "approval expired before execution",
                    started,
                )
            if request.approval_digest() != digest:
                return self._finish_without_execution(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.DENIED,
                    ExecutionErrorCategory.APPROVAL_INVALID,
                    "material execution request changed after approval",
                    started,
                )

        if request.approval_digest() != digest or request.resolved_action_error():
            return self._finish_without_execution(
                request,
                request_id,
                digest,
                ExecutionStatus.BLOCKED,
                ExecutionErrorCategory.UNSUPPORTED_ACTION,
                "material resolved action changed before execution",
                started,
            )

        if not self._record_authorization(request, request_id, digest):
            return self._telemetry_unavailable(request, request_id, digest, started)

        execution_token = _activate_execution(
            request.action,
            request.executor,
            request.target,
        )
        try:
            value = await operation()
        except asyncio.CancelledError:
            result = self._terminal_result(
                request,
                request_id,
                digest,
                ExecutionStatus.CANCELLED,
                False,
                ExecutionErrorCategory.CANCELLATION,
                "execution cancelled",
                started,
            )
            self._record_terminal(request, result)
            raise
        except TimeoutError:
            result = self._terminal_result(
                request,
                request_id,
                digest,
                ExecutionStatus.TIMEOUT,
                False,
                ExecutionErrorCategory.TIMEOUT,
                "execution timed out",
                started,
            )
        except Exception as exc:
            result = self._terminal_result(
                request,
                request_id,
                digest,
                ExecutionStatus.ERROR,
                False,
                ExecutionErrorCategory.EXECUTION_FAILURE,
                self._safe_error(exc),
                started,
            )
        else:
            success = bool(getattr(value, "success", True))
            if success:
                result = self._terminal_result(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.SUCCESS,
                    True,
                    None,
                    "",
                    started,
                    value,
                )
            else:
                timed_out = bool(getattr(value, "timed_out", False))
                error = getattr(value, "error", "") or getattr(value, "stderr", "")
                result = self._terminal_result(
                    request,
                    request_id,
                    digest,
                    ExecutionStatus.TIMEOUT if timed_out else ExecutionStatus.ERROR,
                    False,
                    ExecutionErrorCategory.TIMEOUT
                    if timed_out
                    else ExecutionErrorCategory.EXECUTION_FAILURE,
                    self._safe_text(str(error)) or "execution failed",
                    started,
                    value,
                )

        finally:
            _reset_execution(execution_token)

        if result.value is not None and not self._capture_evidence(request, result):
            result.status = ExecutionStatus.ERROR
            result.success = False
            result.value = None
            result.error_category = ExecutionErrorCategory.TELEMETRY_FAILURE
            result.error = "protected raw evidence could not be persisted"

        if not self._record_terminal(request, result):
            result.status = ExecutionStatus.ERROR
            result.success = False
            result.error_category = ExecutionErrorCategory.TELEMETRY_FAILURE
            result.error = "mandatory execution telemetry could not be recorded"
        return result

    def _finish_without_execution(
        self,
        request: ExecutionRequest,
        request_id: str,
        digest: str,
        status: ExecutionStatus,
        category: ExecutionErrorCategory,
        error: str,
        started: float,
        audit_event: bool = True,
    ) -> CoordinatedResult:
        result = self._terminal_result(
            request,
            request_id,
            digest,
            status,
            False,
            category,
            self._safe_text(error),
            started,
        )
        if not self._record_terminal(
            request,
            result,
            audit_event=audit_event,
            executed=False,
        ):
            result.status = ExecutionStatus.ERROR
            result.error_category = ExecutionErrorCategory.TELEMETRY_FAILURE
            result.error = "mandatory execution telemetry could not be recorded"
        return result

    def _telemetry_unavailable(
        self,
        request: ExecutionRequest,
        request_id: str,
        digest: str,
        started: float,
    ) -> CoordinatedResult:
        result = self._terminal_result(
            request,
            request_id,
            digest,
            ExecutionStatus.ERROR,
            False,
            ExecutionErrorCategory.TELEMETRY_FAILURE,
            "mandatory audit service is unavailable; execution was not started",
            started,
        )
        self._record_non_audit_telemetry(request, result)
        return result

    @staticmethod
    def _terminal_result(
        request: ExecutionRequest,
        request_id: str,
        digest: str,
        status: ExecutionStatus,
        success: bool,
        category: ExecutionErrorCategory | None,
        error: str,
        started: float,
        value: Any = None,
    ) -> CoordinatedResult:
        return CoordinatedResult(
            request_id=request_id,
            action=request.action,
            status=status,
            success=success,
            value=value,
            error_category=category,
            error=error,
            duration=time.perf_counter() - started,
            approval_digest=digest,
        )

    def _record_authorization(
        self,
        request: ExecutionRequest,
        request_id: str,
        digest: str,
    ) -> bool:
        try:
            self._audit.record(
                AuditEvent(
                    timestamp="",
                    event="approval",
                    tool=request.action,
                    target=self._safe_text(request.target),
                    risk=request.risk.value,
                    approved=True,
                    detail="execution authorized",
                    metadata={
                        "request_id": request_id,
                        "approval_digest": digest,
                        "executor": request.executor,
                        "required_privileges": request.required_privileges,
                        "credential_refs": request.credential_refs,
                        "execution_identity": request.execution_identity.model_dump(),
                        "resolved_action": request.resolved_action.telemetry_summary()
                        if request.resolved_action
                        else {},
                        "approval_expires_at": request.approval_expires_at.isoformat()
                        if request.approval_expires_at
                        else "",
                    },
                )
            )
        except Exception:
            return False
        return True

    def _record_terminal(
        self,
        request: ExecutionRequest,
        result: CoordinatedResult,
        audit_event: bool = True,
        executed: bool = True,
    ) -> bool:
        ok = True
        if audit_event:
            event = "tool_execution" if executed else "rejection"
            try:
                self._audit.record(
                    AuditEvent(
                        timestamp="",
                        event=event,
                        tool=request.action,
                        target=self._safe_text(request.target),
                        risk=request.risk.value,
                        approved=executed,
                        detail=result.status.value,
                        metadata={
                            "request_id": result.request_id,
                            "approval_digest": result.approval_digest,
                            "error_category": result.error_category.value
                            if result.error_category
                            else "",
                            "executor": request.executor,
                            "execution_identity": request.execution_identity.model_dump(),
                            "resolved_action": request.resolved_action.telemetry_summary()
                            if request.resolved_action
                            else {},
                            "evidence": result.evidence.model_dump()
                            if result.evidence
                            else {},
                        },
                    )
                )
            except Exception:
                ok = False
        return self._record_non_audit_telemetry(request, result) and ok

    def _record_non_audit_telemetry(
        self,
        request: ExecutionRequest,
        result: CoordinatedResult,
    ) -> bool:
        ok = True
        metadata = {
            "request_id": result.request_id,
            "approval_digest": result.approval_digest,
            "target": self._safe_text(request.target),
            "risk": request.risk.value,
            "executor": request.executor,
            "execution_identity": request.execution_identity.model_dump(),
            "resolved_action": request.resolved_action.telemetry_summary()
            if request.resolved_action
            else {},
            "required_privileges": request.required_privileges,
            "credential_refs": request.credential_refs,
            "approval_expires_at": request.approval_expires_at.isoformat()
            if request.approval_expires_at
            else "",
            "evidence": result.evidence.model_dump() if result.evidence else {},
            "error_category": result.error_category.value
            if result.error_category
            else "",
        }
        try:
            self._logging.log_execution(
                tool=request.action,
                command="[redacted]" if request.command else "",
                status=result.status.value,
                duration=result.duration,
                output_file=result.evidence.path if result.evidence else "",
                error=result.error_category.value if result.error_category else "",
                metadata=metadata,
            )
        except Exception:
            ok = False
        try:
            self._feedback.record_execution(
                ExecutionFeedback(
                    skill=request.action,
                    success=result.success,
                    execution_time=result.duration,
                    dependency_missing=(
                        result.error_category
                        == ExecutionErrorCategory.MISSING_DEPENDENCY
                    ),
                    error=result.error_category.value if result.error_category else "",
                    metadata=metadata,
                )
            )
        except Exception:
            ok = False
        return ok

    def _capture_evidence(
        self,
        request: ExecutionRequest,
        result: CoordinatedResult,
    ) -> bool:
        try:
            result.evidence = self._evidence.capture(
                {
                    "request_id": result.request_id,
                    "action": request.action,
                    "target": request.target,
                    "status": result.status.value,
                    "value": result.value,
                },
                evidence_id=result.request_id,
            )
        except Exception:
            return False
        return True

    @classmethod
    def _safe_error(cls, error: Exception) -> str:
        return cls._safe_text(f"{type(error).__name__}: {error}")

    @classmethod
    def _safe_text(cls, value: str) -> str:
        return cls._redact_text(value)[:500]

    @classmethod
    def _redact_text(cls, value: str) -> str:
        return str(redact_sensitive(value))

    @classmethod
    def _safe_value(cls, value: Any, key: str = "") -> Any:
        return redact_sensitive(value, key)
