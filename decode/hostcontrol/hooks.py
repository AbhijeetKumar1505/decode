"""Pre/post-execution hooks — a governed extension point.

Hooks observe (and pre-hooks may veto) governed execution. They cannot grant
permission: a pre-hook can only *deny*, never upgrade a decision. This mirrors
Claude-Code-style hooks while preserving the fail-closed model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..skills.base import RiskLevel


@dataclass
class HookEvent:
    phase: str  # "pre" or "post"
    capability: str
    risk: RiskLevel = RiskLevel.READ
    target: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# A pre-hook returns (allow, reason); a post-hook returns None.
PreHook = Callable[[HookEvent], tuple[bool, str]]
PostHook = Callable[[HookEvent, Any], None]


class HookRegistry:
    def __init__(self) -> None:
        self._pre: list[PreHook] = []
        self._post: list[PostHook] = []

    def register_pre(self, hook: PreHook) -> None:
        self._pre.append(hook)

    def register_post(self, hook: PostHook) -> None:
        self._post.append(hook)

    def run_pre(self, event: HookEvent) -> tuple[bool, str]:
        """Run pre-hooks. The first veto denies; a raising hook fails closed."""
        for hook in self._pre:
            try:
                allow, reason = hook(event)
            except Exception as exc:  # a misbehaving hook must not open the gate
                return False, f"pre-hook error: {type(exc).__name__}"
            if not allow:
                return False, reason or "denied by pre-execution hook"
        return True, ""

    def run_post(self, event: HookEvent, outcome: Any) -> None:
        for hook in self._post:
            try:
                hook(event, outcome)
            except Exception:
                continue  # post-hooks are observational; never fail execution
