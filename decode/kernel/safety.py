from collections.abc import Callable
from enum import Enum
from typing import Any

from ..skills.base import RiskLevel


class Permission(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class SafetyController:
    def __init__(self, approval_callback: Callable | None = None):
        self._approval_callback = approval_callback
        self._prohibited_actions: list[str] = []
        self._override_rules: dict[str, Permission] = {}

    def prohibit(self, action: str):
        self._prohibited_actions.append(action.lower())

    def set_override(self, skill_name: str, permission: Permission):
        self._override_rules[skill_name.lower()] = permission

    async def check(
        self, skill_name: str, risk_level: RiskLevel, params: dict[str, Any]
    ) -> Permission:
        skill_lower = skill_name.lower()
        if skill_lower in self._override_rules:
            return self._override_rules[skill_lower]
        if skill_lower in [a.lower() for a in self._prohibited_actions]:
            return Permission.DENY
        if risk_level == RiskLevel.READ:
            return Permission.ALLOW
        if risk_level == RiskLevel.DESTRUCTIVE:
            return Permission.DENY
        if risk_level == RiskLevel.WRITE:
            if self._approval_callback:
                approved = await self._approval_callback(skill_name, params)
                return Permission.ALLOW if approved else Permission.DENY
            return Permission.REQUIRE_APPROVAL
        return Permission.REQUIRE_APPROVAL
