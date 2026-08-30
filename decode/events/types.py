"""Typed runtime events.

The runtime publishes these to an :class:`~decode.events.bus.EventBus`; any
frontend (the inline REPL, the Textual console, later a Web UI or API) folds them
into its own view. The TUI never controls tools directly — it sends input to the
runtime and renders the events that come back.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Event(BaseModel):
    ts: str = Field(default_factory=_now)

    @property
    def kind(self) -> str:
        return type(self).__name__


class SessionStarted(Event):
    goal: str = ""
    mode: str = "hybrid"


class AgentStatus(Event):
    #: ready | thinking | planning | executing | needs_approval | complete | error
    status: str = "ready"


class AgentThought(Event):
    text: str = ""


class PlanUpdated(Event):
    summary: str = ""  # compact task-state render


class ToolStarted(Event):
    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""


class ToolCompleted(Event):
    tool: str
    success: bool = False
    summary: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    duration: float = 0.0


class ApprovalRequired(Event):
    request_id: str
    action: str
    target: str = ""
    risk: str = ""
    command: str = ""


class ApprovalResolved(Event):
    request_id: str
    approved: bool


class FindingCreated(Event):
    title: str
    severity: str = "info"
    detail: str = ""


class FileChanged(Event):
    path: str
    change: str = ""


class TokensUpdated(Event):
    session_tokens: int = 0
    step_tokens: int = 0


class ErrorOccurred(Event):
    message: str = ""


class FinalMessage(Event):
    message: str = ""
