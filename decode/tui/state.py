"""TUI state store — folds runtime events into renderable view state.

Frontend-agnostic: the Textual console and any other UI read this instead of
re-deriving state from raw events. One ``apply(event)`` call updates the view and
returns the changed regions so a frontend can refresh selectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..events import (
    AgentStatus,
    AgentThought,
    ApprovalRequired,
    ApprovalResolved,
    ErrorOccurred,
    Event,
    FinalMessage,
    FindingCreated,
    PlanUpdated,
    SessionStarted,
    TokensUpdated,
    ToolCompleted,
    ToolStarted,
)


@dataclass
class Entry:
    kind: str  # thought | tool_call | tool_result | final | error | approval
    text: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    title: str
    severity: str = "info"
    detail: str = ""


@dataclass
class SessionView:
    goal: str = ""
    mode: str = "hybrid"
    status: str = "ready"
    session_tokens: int = 0
    step_tokens: int = 0
    plan_summary: str = ""
    final: str = ""
    entries: List[Entry] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    current_tool: str = ""


class TUIStore:
    def __init__(self) -> None:
        self.view = SessionView()

    def apply(self, event: Event) -> List[str]:
        """Fold one event into the view; return the names of changed regions."""
        view = self.view
        if isinstance(event, SessionStarted):
            self.view = SessionView(goal=event.goal, mode=event.mode, status="thinking")
            return ["header", "session", "findings", "plan"]
        if isinstance(event, AgentStatus):
            view.status = event.status
            return ["header"]
        if isinstance(event, TokensUpdated):
            view.session_tokens = event.session_tokens
            view.step_tokens = event.step_tokens
            return ["header"]
        if isinstance(event, AgentThought):
            if event.text:
                view.entries.append(Entry(kind="thought", text=event.text))
            return ["session"]
        if isinstance(event, ToolStarted):
            view.current_tool = event.tool
            view.entries.append(Entry(kind="tool_call", text=event.tool, data={"params": event.params, "source": event.source}))
            return ["session"]
        if isinstance(event, ToolCompleted):
            view.current_tool = ""
            view.entries.append(Entry(
                kind="tool_result", text=event.tool,
                data={"success": event.success, "summary": event.summary, "data": event.data, "duration": event.duration},
            ))
            return ["session"]
        if isinstance(event, PlanUpdated):
            view.plan_summary = event.summary
            return ["plan"]
        if isinstance(event, ApprovalRequired):
            view.entries.append(Entry(kind="approval", text=event.action,
                                      data={"target": event.target, "risk": event.risk, "command": event.command}))
            return ["session"]
        if isinstance(event, ApprovalResolved):
            return []
        if isinstance(event, FindingCreated):
            view.findings.append(Finding(title=event.title, severity=event.severity, detail=event.detail))
            return ["findings"]
        if isinstance(event, ErrorOccurred):
            view.status = "error"
            view.entries.append(Entry(kind="error", text=event.message))
            return ["header", "session"]
        if isinstance(event, FinalMessage):
            view.final = event.message
            view.entries.append(Entry(kind="final", text=event.message))
            return ["session"]
        return []
