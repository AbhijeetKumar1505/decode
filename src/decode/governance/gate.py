"""Governance gate — the single pre-execution decision point.

Combines two controls the v1 code never enforced together:
  1. Scope: is the target authorized? (hard block, audited)
  2. Risk:  READ auto-allows, WRITE needs approval, DESTRUCTIVE needs an
            explicit engagement override *and* approval.

Every denial is written to the audit trail so refusals are as accountable as
executions.
"""

import re
from enum import Enum

from pydantic import BaseModel

from ..audit import AuditEvent, AuditLayer
from ..hostcontrol.policy import PermissionMode
from .scope import ScopePolicy


class Decision(str, Enum):
    ALLOW = "allow"
    NEEDS_APPROVAL = "needs_approval"
    DENY = "deny"


class GovernanceDecision(BaseModel):
    decision: Decision
    reason: str = ""


class GovernanceGate:
    _SECRET_PATTERN = re.compile(
        r"(?i)(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*([^\s,;]+)"
    )
    _BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")

    def __init__(
        self,
        scope: ScopePolicy,
        audit: AuditLayer | None = None,
        allow_destructive: bool = False,
        mode: PermissionMode = PermissionMode.ASK,
    ):
        self._scope = scope
        self._audit = audit or AuditLayer()
        self._allow_destructive = allow_destructive
        self._mode = mode

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    def set_mode(self, mode: PermissionMode) -> None:
        self._mode = mode

    @property
    def audit(self) -> AuditLayer:
        return self._audit

    def evaluate(
        self,
        capability: str,
        target: str,
        risk: str,
        *,
        target_required: bool = False,
    ) -> GovernanceDecision:
        risk = (risk or "WRITE").upper()

        if target_required and not target.strip():
            reason = "explicit target is required for this capability"
            self._record(
                "rejection",
                capability,
                "",
                risk,
                approved=False,
                detail=reason,
            )
            return GovernanceDecision(decision=Decision.DENY, reason=reason)

        if target and not self._scope.is_in_scope(target):
            safe_target = self._safe_text(target)
            reason = f"target '{safe_target}' is out of engagement scope"
            self._record(
                "rejection",
                capability,
                safe_target,
                risk,
                approved=False,
                detail=reason,
            )
            return GovernanceDecision(decision=Decision.DENY, reason=reason)

        # Plan mode never executes — it only surfaces what would run.
        if self._mode is PermissionMode.PLAN:
            reason = "plan mode: execution disabled"
            self._record(
                "rejection",
                capability,
                self._safe_text(target),
                risk,
                approved=False,
                detail=reason,
            )
            return GovernanceDecision(decision=Decision.DENY, reason=reason)

        if risk == "READ":
            return GovernanceDecision(
                decision=Decision.ALLOW, reason="read-only, in scope"
            )

        if risk == "DESTRUCTIVE":
            if not self._allow_destructive:
                reason = "destructive capability requires explicit engagement override"
                self._record(
                    "rejection",
                    capability,
                    self._safe_text(target),
                    risk,
                    approved=False,
                    detail=reason,
                )
                return GovernanceDecision(decision=Decision.DENY, reason=reason)
            return GovernanceDecision(
                decision=Decision.NEEDS_APPROVAL,
                reason="destructive: override set, human approval still required",
            )

        # WRITE (and anything else): auto mode allows in-scope writes; otherwise approval.
        if self._mode is PermissionMode.AUTO:
            return GovernanceDecision(
                decision=Decision.ALLOW, reason="auto mode: write allowed in scope"
            )
        return GovernanceDecision(
            decision=Decision.NEEDS_APPROVAL, reason="requires human approval"
        )

    def _record(self, event, capability, target, risk, approved, detail):
        self._audit.record(
            AuditEvent(
                timestamp="",
                event=event,
                tool=capability,
                target=target,
                risk=risk,
                approved=approved,
                detail=detail,
            )
        )

    @classmethod
    def _safe_text(cls, value: str) -> str:
        text = cls._SECRET_PATTERN.sub(r"\1=[REDACTED]", value)
        return cls._BEARER_PATTERN.sub("Bearer [REDACTED]", text)[:500]
