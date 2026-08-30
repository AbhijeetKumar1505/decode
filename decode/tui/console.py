"""Full-screen Textual console for De-code (`decode tui`).

A terminal-native agent console: header (status/mode/tokens/cwd), a workspace
pane (files + tool sources), a session pane (thoughts, tool cards, findings), and
an input bar. It never drives tools directly — it sends the user's goal to the
runtime and renders the typed events that come back over the event bus, with a
first-class approval modal. The inline REPL remains the default `decode`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Input, RichLog, Static

from ..events import (
    AgentStatus,
    AgentThought,
    ApprovalRequired,
    ApprovalResolved,
    ErrorOccurred,
    FinalMessage,
    FindingCreated,
    PlanUpdated,
    SessionStarted,
    TokensUpdated,
    ToolCompleted,
    ToolStarted,
    EventBus,
)
from ..hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from .state import TUIStore

_STATUS_ICON = {
    "ready": "●", "thinking": "◉", "planning": "◌", "executing": "⚡",
    "needs_approval": "!", "complete": "✓", "error": "×",
}


class ApprovalModal(ModalScreen[str]):
    """Blocking approval prompt. Dismisses with 'once' | 'session' | 'deny'."""

    BINDINGS = [
        ("y", "resolve('once')", "Allow once"),
        ("a", "resolve('session')", "Allow session"),
        ("n", "resolve('deny')", "Deny"),
        ("escape", "resolve('deny')", "Deny"),
    ]

    def __init__(self, request: Any) -> None:
        super().__init__()
        self._request = request

    def compose(self) -> ComposeResult:
        r = self._request
        risk = getattr(r.risk, "value", str(r.risk))
        body = Text()
        body.append("De-code wants to execute:\n\n", style="bold")
        body.append(f"  {r.command or r.action}\n\n", style="yellow")
        body.append(f"Action:  {r.action}\n")
        body.append(f"Target:  {r.target or '-'}\n")
        body.append(f"Risk:    {risk}\n\n")
        body.append("[Y] Allow once    [A] Allow session    [N] Deny", style="bold")
        yield Vertical(
            Static(Panel(body, title="ACTION REQUIRES APPROVAL", border_style="yellow")),
            id="approval-box",
        )

    def action_resolve(self, choice: str) -> None:
        self.dismiss(choice)


class DecodeConsole(App):
    CSS = """
    Screen { layout: vertical; }
    #header { height: 1; background: $panel; color: $text; padding: 0 1; }
    #body { height: 1fr; }
    #workspace { width: 32; border-right: solid $panel; }
    #session-pane { width: 1fr; }
    .pane-title { color: $text-muted; text-style: bold; padding: 0 1; }
    #files { height: 1fr; }
    #tools { height: auto; color: $text-muted; padding: 0 1; }
    #session { height: 1fr; padding: 0 1; }
    #findings { height: auto; padding: 0 1; }
    #input { dock: bottom; }
    #approval-box { align: center middle; width: 70; }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, agent: Any, *, mcp_manager: Any = None) -> None:
        super().__init__()
        self._agent = agent
        self._mcp = mcp_manager
        self._bus = EventBus()
        self._store = TUIStore()
        self._perm_mode = PermissionMode.ASK
        self._fs_scope = FilesystemScope(read_roots=[Path.cwd()])
        self._cmd_policy = CommandPolicy()
        self._auto_approve = False

    # ── layout ──────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="header")
        with Horizontal(id="body"):
            with Vertical(id="workspace"):
                yield Static("WORKSPACE", classes="pane-title")
                yield DirectoryTree(str(Path.cwd()), id="files")
                yield Static(self._tools_text(), id="tools")
            with Vertical(id="session-pane"):
                yield Static("SESSION", classes="pane-title")
                yield RichLog(id="session", wrap=True, markup=False, highlight=False)
                yield Static("", id="findings")
        yield Input(placeholder="Ask De-code…   (Ctrl+C to quit)", id="input")

    def on_mount(self) -> None:
        self._bus.subscribe(self._on_event)
        self.query_one("#input", Input).focus()

    # ── rendering ───────────────────────────────────────────────────────
    def _header_text(self) -> Text:
        v = self._store.view
        icon = _STATUS_ICON.get(v.status, "●")
        text = Text()
        text.append("DE-CODE ", style="bold")
        text.append(f" {icon} {v.status.upper()} ", style="bold cyan")
        text.append(f" │ {v.mode} │ {v.session_tokens} tok │ {Path.cwd().name}", style="dim")
        return text

    def _tools_text(self) -> Text:
        text = Text()
        text.append("SYSTEM\n", style="bold")
        for name in ("shell", "filesystem", "process", "network", "git"):
            text.append(f"  {name}\n", style="dim")
        text.append("SPECIALIZED\n", style="bold")
        try:
            from ..extensions import ExtensionManager

            mgr = ExtensionManager()
            names = list(mgr.mcp.list_servers()) + list(mgr.plugins.list_plugins())
        except Exception:
            names = []
        if names:
            for name in names:
                text.append(f"  {name}\n", style="dim")
        else:
            text.append("  (none configured)\n", style="dim")
        return text

    def _tool_card(self, event: ToolCompleted) -> Panel:
        data = event.data or {}
        body = Text()
        if "stdout" in data or "exit_code" in data:
            if data.get("exit_code") is not None:
                body.append(f"exit {data.get('exit_code')}\n", style="dim")
            out = str(data.get("stdout", "") or data.get("stderr", "")).strip()
            if out:
                body.append(out[:600])
        else:
            body.append(event.summary[:600] or "ok")
        status = "✓" if event.success else "×"
        style = "green" if event.success else "red"
        return Panel(body, title=f"{status} {event.tool}", border_style=style, title_align="left")

    def _on_event(self, event: Any) -> None:
        self._store.apply(event)
        log = self.query_one("#session", RichLog)
        if isinstance(event, SessionStarted):
            log.write(Text(f"> {event.goal}", style="bold"))
        elif isinstance(event, AgentThought) and event.text:
            log.write(Text(f"› {event.text}", style="dim italic"))
        elif isinstance(event, ToolStarted):
            params = json.dumps(event.params, default=str)[:80]
            log.write(Text(f"⚡ {event.tool} {params}", style="cyan"))
        elif isinstance(event, ToolCompleted):
            log.write(self._tool_card(event))
        elif isinstance(event, FinalMessage):
            log.write(Panel(event.message or "(done)", title="RESULT", border_style="green", title_align="left"))
        elif isinstance(event, ErrorOccurred):
            log.write(Text(f"× {event.message}", style="red"))
        if isinstance(event, (AgentStatus, TokensUpdated, SessionStarted)):
            self.query_one("#header", Static).update(self._header_text())
        if isinstance(event, (PlanUpdated, FindingCreated)):
            self._render_findings()

    def _render_findings(self) -> None:
        findings = self._store.view.findings
        if not findings:
            return
        text = Text("FINDINGS\n", style="bold")
        for finding in findings[-6:]:
            text.append(f"  {finding.severity.upper():8} {finding.title}\n", style="yellow")
        self.query_one("#findings", Static).update(text)

    # ── driving the runtime ─────────────────────────────────────────────
    async def _approve(self, request: Any) -> bool:
        risk = getattr(request.risk, "value", str(request.risk))
        await self._bus.emit(ApprovalRequired(
            request_id=request.request_id, action=request.action,
            target=request.target, risk=risk, command=request.command,
        ))
        if self._auto_approve:
            await self._bus.emit(ApprovalResolved(request_id=request.request_id, approved=True))
            return True
        choice = await self.push_screen_wait(ApprovalModal(request))
        approved = choice in ("once", "session")
        if choice == "session":
            self._auto_approve = True
        await self._bus.emit(ApprovalResolved(request_id=request.request_id, approved=approved))
        return approved

    def on_input_submitted(self, event: Input.Submitted) -> None:
        goal = (event.value or "").strip()
        if not goal:
            return
        self.query_one("#input", Input).value = ""
        self.run_worker(self._drive(goal), exclusive=True)

    async def _drive(self, goal: str) -> None:
        try:
            await self._agent.run_tool_loop(
                goal,
                filesystem_scope=self._fs_scope,
                command_policy=self._cmd_policy,
                permission_mode=self._perm_mode,
                approval_callback=self._approve,
                event_bus=self._bus,
                mcp_manager=self._mcp,
            )
        except Exception as exc:  # surface, never crash the console
            await self._bus.emit(ErrorOccurred(message=f"{type(exc).__name__}: {exc}"))


def run_console(agent: Any, *, mcp_manager: Any = None) -> None:
    DecodeConsole(agent, mcp_manager=mcp_manager).run()
