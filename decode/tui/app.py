"""Simple Rich + prompt_toolkit REPL — inline terminal like Claude Code."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.panel import Panel
from rich.json import JSON
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.formatted_text import HTML

from rich.prompt import Confirm, Prompt

from decode.logging_service import LoggingService
from decode.skills.registry import SkillRegistry
from decode.persistence import create_store
from decode.persistence.target_tracker import TargetContextTracker, TargetFinding
from decode.persistence.evidence import EvidenceCollector
from decode.runtime import redact_sensitive
from decode.hostcontrol import CommandPolicy, FilesystemScope, PermissionMode

console = Console()

# Single source of truth for help, autocompletion, and the /help <command> detail
# view. group -> list of (command, args, short description, long detail).
COMMAND_GROUPS: Dict[str, List[tuple]] = {
    "Universal agent (governed)": [
        ("(just type)", "<goal or question>", "Talk to the universal agent",
         "Natural-language goals and questions run through the governed tool-use loop: it discovers installed tools (list_tools), drives them via shell_command, and answers directly. Same path as /agent."),
        ("/agent", "<goal>", "Run the governed tool-use loop explicitly",
         "The model drives a bounded plan→call→observe loop over host operations and installed tools, each governed. READ runs freely; WRITE/DESTRUCTIVE are gated."),
        ("/scope", "[targets]", "Show or set authorized scope",
         "Set the allowlist of authorized CIDRs, hosts, or domains. Empty scope denies target execution."),
        ("/providers", "", "Execution providers + health",
         "Show local/Docker/WSL/SSH/MCP providers and their health."),
        ("/knowledge", "<query>", "Search the knowledge base",
         "Search the local knowledge graph for entities relevant to a query."),
    ],
    "Host control (governed OS operations)": [
        ("/mode", "[plan|ask|auto]", "Show or set the permission mode",
         "plan = never execute (preview only); ask = READ auto, WRITE/DESTRUCTIVE need approval; auto = READ+WRITE auto in scope, DESTRUCTIVE still gated."),
        ("/fsscope", "<read> [write]", "Set the filesystem scope",
         "Authorize a read root (and optional write root) for file operations. Defaults to the working directory, read-only."),
        ("/read", "<path>", "Read a file (governed)", "Read a file within the authorized filesystem scope."),
        ("/ls", "[path]", "List a directory (governed)", "List a directory within the authorized scope."),
        ("/ps", "", "List processes (governed)", "List running processes."),
        ("/run", "<command>", "Run a policy-checked command", "Run an argument-vector command; risk is classified and gated (no raw shell)."),
        ("!", "<command>", "Shell mode: run a command directly",
         "Prefix any line with ! to run it as a governed command, e.g. `! nmap -sV 10.0.0.5`. For `! sudo ...` you are prompted for your sudo password in the CLI (sent only to sudo, never logged or shown to the model)."),
    ],
    "Model": [
        ("/model", "[id]", "Show or switch the active model",
         "With no argument, list available models with their TPM/RPS limits. With an id (bare name or provider/name, e.g. devstral-2512), switch the active model."),
    ],
    "Session": [
        ("/start", "[target]", "Start a new assessment session", "Begin a session, optionally pinning a target."),
        ("/target", "[ip]", "Show or set the session target", "Show the current target, or set it."),
        ("/session", "", "Show active session context", "Show session goal, target, findings, and evidence counts."),
        ("/findings", "", "List findings in the current session", "List recorded findings with severity."),
        ("/evidence", "", "Show collected evidence", "List evidence captured this session."),
        ("/resume", "<id>", "Resume a previous session", "Reload a saved session by id."),
    ],
    "General": [
        ("/plugins", "", "List available skills", "List all auto-discovered skills with risk and category."),
        ("/skills", "", "Alias for /plugins", "List all auto-discovered skills."),
        ("/tools", "", "List available tools", "List skills as callable tools."),
        ("/logs", "[filter]", "Show recent logs", "Show recent structured execution logs, optionally filtered."),
        ("/help", "[command]", "Show help, or details for one command", "With no argument, list all commands. With a command, show its detail."),
        ("/clear", "", "Clear conversation history", "Reset the conversation context."),
        ("/exit", "", "Exit Decode", "Quit the REPL (or press Ctrl+D)."),
    ],
}


def _command_index() -> Dict[str, tuple]:
    index: Dict[str, tuple] = {}
    for rows in COMMAND_GROUPS.values():
        for cmd, args, short, detail in rows:
            index[cmd] = (args, short, detail)
    return index


class AgentREPL:
    """Simple REPL with Rich output and prompt_toolkit input."""

    def __init__(self, agent, domain: str = "redteam", resume: Optional[str] = None,
                 continue_last: bool = False):
        self._agent = agent
        self._resume_request = resume
        self._continue_last = continue_last
        self._last_interrupt = 0.0
        # Host control: default read scope = cwd, no write scope, permissive command
        # classification. Everything still flows through the governed coordinator.
        self._perm_mode = PermissionMode.ASK
        self._fs_scope = FilesystemScope(read_roots=[Path.cwd()])
        self._cmd_policy = CommandPolicy()
        self._host_ctl = None
        self._host_gate = None
        self._domain = domain
        self._model = getattr(agent, 'provider_name', 'openrouter')
        self._store = create_store()
        self._log_svc = LoggingService()
        self._tracker: Optional[TargetContextTracker] = None
        self._evidence = EvidenceCollector()
        self._registry = SkillRegistry()
        self._session_active = False
        self._current_target: str = ""
        self._scope_entries: List[str] = []
        if hasattr(self._agent, "set_scope"):
            self._agent.set_scope([])
        self._pending_action: Optional[Dict[str, Any]] = None
        self._last_response: Optional[Dict[str, Any]] = None
        self._conversation_history: List[Dict[str, str]] = (
            getattr(agent, "conversation_history", []) if agent else []
        )

        self._finding_type_map = {
            "nmap_pro": ("reconnaissance", "high"),
            "web_vuln_scan": ("vulnerability", "high"),
            "dir_bruteforce": ("discovery", "medium"),
            "cve_lookup": ("vulnerability", "medium"),
            "host_profiler": ("reconnaissance", "medium"),
            "network_mapper": ("reconnaissance", "medium"),
            "web_scan": ("vulnerability", "high"),
            "threat_intel": ("intelligence", "medium"),
            "report_engine": ("reporting", "low"),
            "evidence_core": ("forensics", "low"),
            "agent_core": ("automation", "low"),
            "social_ir": ("social_engineering", "high"),
            "phishing_investigator": ("social_engineering", "high"),
            "credential_watch": ("credential_monitoring", "high"),
            "malware_intel": ("malware_analysis", "high"),
            "timeline_engine": ("forensics", "medium"),
            "cloud_security": ("cloud_security", "high"),
            "ad_enum": ("active_directory", "high"),
            "k8s_audit": ("container_security", "high"),
            "attack_graph": ("attack_path", "high"),
        }

        self._history_path = Path("./data/repl_history.txt")
        self._history_path.parent.mkdir(parents=True, exist_ok=True)

        self._commands = _command_index()
        completer = NestedCompleter.from_nested_dict({
            cmd: (
                {name.lstrip("/"): None for name in self._commands}
                if cmd == "/help"
                else None
            )
            for cmd in self._commands
        })

        # Ctrl+C cancels the current line/op (handled in run()); Ctrl+D exits.
        self._session = PromptSession(
            history=FileHistory(str(self._history_path)),
            completer=completer,
            complete_while_typing=True,
            style=PTStyle([("prompt", "bold cyan")]),
            bottom_toolbar=self._get_bottom_toolbar,
        )

    def run(self):
        self._print_welcome()
        self._apply_resume_request()
        while True:
            try:
                text = self._session.prompt(self._prompt())
            except KeyboardInterrupt:
                # Claude Code style: first Ctrl+C warns, a quick second one exits.
                now = time.monotonic()
                if now - self._last_interrupt < 2.0:
                    self._exit()
                    break
                self._last_interrupt = now
                console.print("[dim]Press Ctrl+C again to exit, or /exit.[/dim]")
                continue
            except EOFError:
                self._exit()
                break  # Ctrl+D exits
            self._last_interrupt = 0.0  # any input resets the double-tap window
            text = text.strip()
            if not text:
                continue
            if text.startswith("!"):
                self._run(self._handle_shell(text[1:].strip()))
                continue
            if text.startswith("/model"):
                self._handle_model(text[len("/model"):].strip())
                continue
            if text in ("/exit", "/quit", "exit", "quit"):
                self._exit()
                break
            if text == "/help" or text.startswith("/help "):
                self._print_help(text[len("/help "):].strip() if " " in text else "")
                continue
            if text == "/clear":
                self._conversation_history.clear()
                console.print("[dim]Conversation history cleared.[/dim]")
                continue
            if text in ("/plugins", "/skills"):
                self._print_plugins()
                continue
            if text == "/tools":
                self._print_tools()
                continue
            if text.startswith("/logs"):
                self._handle_logs(text)
                continue
            if text == "/session":
                self._show_session()
                continue
            if text.startswith("/resume "):
                self._handle_resume(text)
                continue
            if text.startswith("/target"):
                self._handle_target(text)
                continue
            if text.startswith("/start"):
                self._handle_start(text)
                continue
            if text.startswith("/scope"):
                self._handle_scope(text)
                continue
            if text == "/providers":
                self._handle_providers()
                continue
            if text.startswith("/knowledge "):
                self._handle_knowledge(text[len("/knowledge "):].strip())
                continue
            if text.startswith("/mode"):
                self._handle_mode(text[len("/mode"):].strip())
                continue
            if text.startswith("/fsscope"):
                self._handle_fsscope(text[len("/fsscope"):].strip())
                continue
            if text.startswith("/read "):
                self._run(self._handle_host("file_read", {"path": text[len("/read "):].strip()}))
                continue
            if text.startswith("/ls"):
                self._run(self._handle_host("file_list", {"path": text[len("/ls"):].strip() or "."}))
                continue
            if text == "/ps":
                self._run(self._handle_host("process_list", {}))
                continue
            if text.startswith("/run "):
                self._run(self._handle_host("shell_command", {"command": text[len("/run "):].strip()}))
                continue
            if text.startswith("/agent "):
                self._run(self._handle_agent(text[len("/agent "):].strip()))
                continue
            if text in ("/findings", "/evidence"):
                if text == "/findings":
                    self._show_findings()
                else:
                    self._show_evidence()
                continue
            if self._pending_action:
                if text.lower() in ("y", "yes", ""):
                    pending = self._pending_action
                    self._pending_action = None
                    if pending.get("type") == "command":
                        self._run(self._execute_command(pending["command"]))
                    else:
                        self._run(self._execute_tool(pending["action"], pending.get("params", {})))
                elif text.lower() in ("n", "no"):
                    console.print("[dim yellow]Action rejected.[/dim yellow]")
                    self._conversation_history.append({
                        "role": "user",
                        "content": "Action rejected. Propose an alternative.",
                    })
                    self._pending_action = None
                else:
                    console.print("[dim yellow]Please answer y or n.[/dim yellow]")
                continue
            self._run(self._chat_loop(text))

    def _exit(self):
        if self._session_active:
            self._save_session()
            self._print_resume_hint()
        console.print("[dim]Goodbye.[/dim]")

    def _print_resume_hint(self):
        if not self._tracker:
            return
        sid = self._tracker.session_id
        console.print(Panel(
            "Session saved. Resume it exactly as it was with:\n\n"
            f"  [cyan]decode --resume {sid}[/cyan]   [dim](from your shell)[/dim]\n"
            f"  [cyan]decode --continue[/cyan]{' ' * max(0, len(sid) - 8)}          [dim](most recent session)[/dim]\n"
            f"  [cyan]/resume {sid}[/cyan]   [dim](inside a running Decode)[/dim]",
            title="Resume", border_style="cyan", box=box.ROUNDED,
        ))

    def _apply_resume_request(self):
        if self._resume_request:
            self._resume_session(self._resume_request)
        elif self._continue_last:
            self._resume_latest()

    def _resume_latest(self):
        sessions = self._store.list_sessions(limit=1)
        if not sessions:
            console.print("[yellow]No previous session to continue.[/yellow]")
            return
        self._resume_session(sessions[0]["id"])

    def _resume_session(self, sid: str):
        session = self._store.get_session(sid)
        if not session:
            console.print(f"[red]Session not found: {sid}[/red]")
            return
        if self._session_active:
            self._save_session()
        loaded: List[Dict[str, str]] = []
        hp = Path(f"./data/sessions/{sid}.json")
        if hp.exists():
            loaded = json.loads(hp.read_text(encoding="utf-8"))
        # Restore conversation for both the REPL and the agent so chat() has context.
        self._conversation_history = loaded
        if hasattr(self._agent, "conversation_history"):
            self._agent.conversation_history = loaded
        self._tracker = TargetContextTracker(self._store, session_id=sid)
        self._store.update_session(sid, status="active")
        self._current_target = session.get("target_focus", "")
        if not self._scope_entries and self._current_target and hasattr(self._agent, "set_scope"):
            self._agent.set_scope([self._current_target])
        self._session_active = True
        console.print(f"[bold green]✓ Resumed session [bold]{sid}[/bold][/bold green]")
        if session.get("goal"):
            console.print(f"[dim]Goal: {session['goal']}  ·  Target: {self._current_target or '—'}[/dim]")

    def _run(self, coro):
        """Run an async op, letting Ctrl+C cancel just that op (not the REPL)."""
        try:
            return asyncio.run(coro)
        except KeyboardInterrupt:
            console.print("\n[yellow]⨯ Cancelled.[/yellow]")
            return None
        except Exception as exc:  # a failed op must not tear down the REPL
            console.print(f"\n[red]⨯ Error:[/red] {type(exc).__name__}: {exc}")
            return None

    def _prompt(self):
        target = f" <ansiyellow>{self._current_target}</ansiyellow>" if self._current_target else ""
        return HTML(f"<b><ansicyan>decode</ansicyan></b>{target} <ansigreen>❯</ansigreen> ")

    def _print_welcome(self):
        status = "[green]session active[/green]" if self._session_active else "[dim]no session[/dim]"
        console.print(Panel(
            "[bold]Decode[/bold] — governed security assistant\n\n"
            "Type a request in natural language, a [cyan]/command[/cyan], or "
            "[cyan]![/cyan] to run a shell command directly ([cyan]Tab[/cyan] to autocomplete).\n"
            "Examples:  [dim]scan 10.0.0.5 for open ports[/dim]   [dim]! nmap -sV 10.0.0.5[/dim]   "
            "[dim]! sudo apt update[/dim]   [dim]/mode auto[/dim]   [dim]/model devstral-2512[/dim]\n"
            f"[cyan]/help[/cyan] lists everything · [cyan]Ctrl+C[/cyan] cancels "
            f"(twice to quit) · [cyan]Ctrl+D[/cyan] quits    {status}",
            border_style="cyan",
            box=box.ROUNDED,
        ))

    def _get_bottom_toolbar(self):
        session_status = "Active" if self._session_active else "Inactive"
        tool_count = len(self._registry.get_all())
        target_str = f"Target: <b>{self._current_target}</b>  |  " if self._current_target else ""
        scope_str = f"Scope: <b>{len(self._scope_entries)}</b>  |  " if self._scope_entries else ""
        return HTML(
            f" {target_str}"
            f"Model: <b>{self._model}</b>  |  "
            f"Domain: <b>{self._domain}</b>  |  "
            f"{scope_str}"
            f"Skills: <b>{tool_count}</b>  |  "
            f"Session: <b>{session_status}</b>  |  "
            f"<b>Ctrl+C</b> cancel (2× quit)  <b>Ctrl+D</b> quit  <b>/help</b>"
        )

    def _print_help(self, command: str = ""):
        if command:
            self._print_command_detail(command)
            return
        console.print()
        for group, rows in COMMAND_GROUPS.items():
            table = Table(box=box.SIMPLE, title=f"[bold]{group}[/bold]", title_justify="left", pad_edge=False)
            table.add_column("Command", style="cyan", no_wrap=True)
            table.add_column("Args", style="dim")
            table.add_column("Description")
            for cmd, args, short, _detail in rows:
                table.add_row(cmd, args, short)
            console.print(table)
        console.print("[dim]Tip: press [cyan]Tab[/cyan] to autocomplete, or [cyan]/help <command>[/cyan] for details.[/dim]\n")

    def _print_command_detail(self, command: str):
        key = command if command.startswith("/") else f"/{command}"
        entry = self._commands.get(key)
        if not entry:
            console.print(f"[yellow]Unknown command '{command}'. Try /help.[/yellow]")
            return
        args, short, detail = entry
        console.print(Panel(
            f"[bold cyan]{key}[/bold cyan] [dim]{args}[/dim]\n\n{detail}",
            title=short, border_style="cyan", box=box.ROUNDED,
        ))

    def _render_result(self, action, result):
        """Render a skill result as structured output rather than a raw dict dump."""
        if isinstance(result, dict):
            info = result.get("host_info")
            if isinstance(info, dict) and isinstance(info.get("os"), dict):
                self._render_host_profile(info)
                return
            self._render_json(result)
            return
        if isinstance(result, list):
            self._render_json(result)
            return
        console.print(Markdown(str(result)[:2000]))

    def _render_json(self, data):
        try:
            text = json.dumps(data, indent=2, default=str)
        except (TypeError, ValueError):
            console.print(str(data)[:2000])
            return
        if len(text) <= 4000:
            console.print(JSON(text))
        else:
            console.print(f"[dim]{text[:4000]}\n… (truncated)[/dim]")

    def _render_host_profile(self, info: Dict[str, Any]):
        os_info = info.get("os", {})
        rows = [
            ("Host", info.get("host", "")),
            ("OS", f"{os_info.get('os_family', '')} {os_info.get('os_version', '')}".strip()),
            ("Kernel", os_info.get("kernel_release") or os_info.get("kernel_version", "")),
            ("Arch", os_info.get("architecture", "")),
            ("Virtualization", os_info.get("virtualization", "")),
            ("Uptime (h)", f"{os_info.get('uptime_hours', 0):.1f}" if os_info.get("uptime_hours") else ""),
        ]
        body = "\n".join(f"[cyan]{k:<16}[/cyan] {v}" for k, v in rows if v)
        console.print(Panel(body, title="Host profile", border_style="green", box=box.ROUNDED))
        services = [s for s in info.get("services", []) if isinstance(s, dict) and s.get("state") == "active" and s.get("name") not in ("", "●")]
        if services:
            table = Table(title=f"Active services ({len(services)})", box=box.SIMPLE, title_justify="left")
            table.add_column("Service", style="cyan")
            table.add_column("State", style="green")
            for svc in services[:15]:
                table.add_row(svc.get("name", ""), svc.get("state", ""))
            if len(services) > 15:
                table.add_row(f"[dim]… +{len(services) - 15} more[/dim]", "")
            console.print(table)

    def _print_plugins(self):
        plugins = self._registry.list_summary()
        table = Table(title="Available Skills", box=box.ROUNDED)
        table.add_column("Skill", style="green")
        table.add_column("Category", style="cyan")
        table.add_column("Risk")
        table.add_column("Description")
        risk_colors = {"READ": "blue", "WRITE": "yellow", "DESTRUCTIVE": "red"}
        for p in plugins:
            rc = risk_colors.get(p["risk_level"], "white")
            table.add_row(
                f"[bold]{p['name']}[/bold]", p["category"],
                f"[{rc}]{p['risk_level']}[/{rc}]", p["description"][:60],
            )
        console.print()
        console.print(table)
        console.print()

    def _print_tools(self):
        skills = self._registry.get_all()
        console.print()
        console.print("[bold]Available Tools[/bold]")
        for s in skills:
            spec = getattr(s, 'spec', None)
            if spec:
                desc = getattr(spec, 'description', '')
                console.print(f"  [green]✓[/green] [bold]{spec.name}[/bold] [dim]— {desc[:70]}[/dim]")
        console.print()

    def _handle_target(self, text):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            console.print(f"[dim]Target: [bold]{self._current_target or 'not set'}[/bold][/dim]")
            return
        target = parts[1].strip()
        self._current_target = target
        if not self._scope_entries and hasattr(self._agent, "set_scope"):
            self._agent.set_scope([target])
        console.print(f"[dim green]Target set: {target}[/dim green]")
        if not self._session_active:
            self._handle_start(f"/start {target}")
        else:
            self._tracker.target_focus = target

    def _handle_logs(self, text):
        parts = text.split(maxsplit=1)
        filt = parts[1].strip() if len(parts) > 1 else None
        try:
            logs = self._log_svc.get_logs(limit=20, tool_filter=filt)
        except Exception:
            logs = []
        console.print()
        if not logs:
            console.print("[dim yellow]No logs found.[/dim yellow]")
            return
        console.print(f"[bold]Recent Logs{(' [' + filt + ']') if filt else ''}[/bold]")
        for log in logs[:20]:
            ts = log.get('timestamp', '')[:19] if log.get('timestamp') else ''
            tool = log.get('tool', log.get('action', '?'))
            status = log.get('status', log.get('success', ''))
            icon = "[green]OK[/green]" if status in ('success', True) else "[red]ERR[/red]"
            console.print(f"  {icon} [cyan]{ts}[/cyan] [bold]{tool}[/bold]")
        console.print()

    def _show_session(self):
        if not self._session_active or not self._tracker:
            console.print("[dim yellow]No active session. Use /start to begin one.[/dim yellow]")
            return
        ctx = self._store.get_session_context(self._tracker.session_id)
        if ctx and ctx.get("targets"):
            for t in ctx["targets"]:
                host = t.get("hostname") or t.get("ip_address") or "unknown"
                table = Table(title=f"Target: {host}", box=box.ROUNDED)
                table.add_column("Port", style="cyan")
                table.add_column("Service", style="green")
                table.add_column("Product", style="yellow")
                table.add_column("Version")
                for p in t.get("ports", []):
                    table.add_row(str(p["port"]), p.get("service", ""), p.get("product", ""), p.get("version", ""))
                if t.get("ports"):
                    console.print(table)
        findings = ctx.get("findings", []) if ctx else []
        if findings:
            ftable = Table(title="Findings", box=box.ROUNDED)
            ftable.add_column("Severity")
            ftable.add_column("Title")
            ftable.add_column("Category")
            sc = {"critical": "red", "high": "bold red", "medium": "yellow", "low": "blue"}
            for f in findings:
                c = sc.get(f["severity"], "white")
                ftable.add_row(f"[{c}]{f['severity'].upper()}[/{c}]", f["title"], f.get("category", ""))
            console.print(ftable)
        if self._tracker:
            console.print(f"[dim]Active session: [cyan]{self._tracker.session_id}[/cyan][/dim]")
        sessions = self._store.list_sessions(5)
        if sessions:
            console.print("[bold]Recent sessions:[/bold]")
            for s in sessions:
                console.print(
                    f"  [cyan]{s['id'][:8]}...[/cyan] {s.get('goal', '')[:40]} [dim]({s.get('created_at', '')[:19]})[/dim]"
                )

    def _show_findings(self):
        if not self._session_active or not self._tracker:
            console.print("[dim yellow]No active session.[/dim yellow]")
            return
        findings = self._store.get_findings(self._tracker.session_id)
        if not findings:
            console.print("[dim yellow]No findings yet.[/dim yellow]")
            return
        ftable = Table(title=f"Findings ({len(findings)})", box=box.ROUNDED)
        ftable.add_column("Severity")
        ftable.add_column("Title")
        ftable.add_column("Category")
        ftable.add_column("Confidence")
        sc = {"critical": "red", "high": "bold red", "medium": "yellow", "low": "blue"}
        for f in findings:
            c = sc.get(f["severity"], "white")
            ftable.add_row(f"[{c}]{f['severity'].upper()}[/{c}]", f["title"][:50], f.get("category", ""), f.get("confidence", ""))
        console.print(ftable)

    def _show_evidence(self):
        if not self._session_active or not self._tracker:
            console.print("[dim yellow]No active session.[/dim yellow]")
            return
        ev = self._store.get_evidence(session_id=self._tracker.session_id)
        if not ev:
            console.print("[dim yellow]No evidence collected.[/dim yellow]")
            return
        etable = Table(title=f"Evidence ({len(ev)})", box=box.ROUNDED)
        etable.add_column("Type")
        etable.add_column("Label")
        etable.add_column("Source")
        etable.add_column("Created")
        for e in ev[:20]:
            etable.add_row(e.get("type", ""), e.get("label", "")[:40], e.get("source", ""), e.get("created_at", "")[:19])
        console.print(etable)

    def _handle_resume(self, text):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[red]Usage: /resume <session_id>[/red]")
            self._list_resumable()
            return
        self._resume_session(parts[1].strip())

    def _list_resumable(self):
        sessions = self._store.list_sessions(limit=5)
        if not sessions:
            return
        console.print("[dim]Recent sessions:[/dim]")
        for s in sessions:
            console.print(f"  [cyan]{s['id']}[/cyan]  [dim]{s.get('goal', '') or '—'}[/dim]")

    def _handle_start(self, text=""):
        target = ""
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            target = parts[1].strip()
        if self._session_active:
            self._save_session()
        self._current_target = target or self._current_target
        target_focus = self._current_target or "target.example.com"
        if not self._scope_entries and hasattr(self._agent, "set_scope"):
            self._agent.set_scope([target_focus])
        self._tracker = TargetContextTracker(self._store)
        sid = self._tracker.start_session(goal="Penetration test", target_focus=target_focus)
        self._session_active = True
        self._conversation_history.clear()
        console.print(f"[bold green]Session started: [bold]{sid}[/bold][/bold green]")
        console.print(f"[dim]Target: {target_focus}[/dim]")


    # ── scope + providers ──

    def _handle_scope(self, text):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            current = ", ".join(self._scope_entries) or self._current_target or "empty (no target authorized)"
            console.print(f"[dim]Scope: [bold]{current}[/bold][/dim]")
            return
        entries = [e for e in parts[1].replace(",", " ").split() if e]
        self._scope_entries = entries
        if entries and not self._current_target:
            self._current_target = entries[0]
        if hasattr(self._agent, "set_scope"):
            self._agent.set_scope(entries)
        console.print(f"[dim green]Scope set: {', '.join(entries)}[/dim green]")

    def _handle_providers(self):
        import asyncio as _asyncio
        from decode.execution import create_executor, available_provider_names
        table = Table(title="Execution Providers", box=box.ROUNDED)
        table.add_column("Provider", style="cyan")
        table.add_column("Health", style="bold")
        for key in available_provider_names():
            try:
                ok = _asyncio.run(create_executor(key).check_health())
            except Exception:
                ok = False
            table.add_row(key, "[green]available[/green]" if ok else "[yellow]unavailable[/yellow]")
        console.print(table)

    async def _handle_shell(self, command_str):
        """Direct governed shell mode (``! <command>``) with sudo password entry.

        Runs through the same governed ``shell_command`` capability as everything
        else — scope-checked, per-command risk-classified, approved, and audited.
        """
        command_str = command_str.strip()
        if not command_str:
            console.print(
                "[yellow]Usage: [bold]! <shell command>[/bold][/yellow]  "
                "[dim](e.g. [italic]! nmap -sV 10.0.0.5[/italic]  or  [italic]! sudo apt update[/italic])[/dim]"
            )
            return
        try:
            argv = shlex.split(command_str)
        except ValueError as exc:
            console.print(f"[red]Cannot parse command: {exc}[/red]")
            return
        stdin = None
        if argv and Path(argv[0]).name == "sudo":
            pw = self._prompt_sudo_password()
            if pw is None:
                console.print("[yellow]Cancelled — no password entered.[/yellow]")
                return
            stdin = pw + "\n"
        console.print(f"[dim]▶ running:[/dim] [bold]{command_str}[/bold]")
        with console.status("[dim]executing…[/dim]", spinner="dots"):
            result = await self._host_controller().run(
                "shell_command", {"command": command_str}, stdin=stdin
            )
        self._render_host("shell_command", result)

    def _prompt_sudo_password(self):
        console.print(
            "[dim]This command needs sudo. Your password is passed only to sudo "
            "(never echoed, logged, stored, or sent to the model).[/dim]"
        )
        try:
            return Prompt.ask("  [yellow][sudo] password[/yellow]", password=True, console=console)
        except (KeyboardInterrupt, EOFError):
            return None

    def _handle_model(self, arg):
        from decode.config import Config
        from decode.models import default_model_registry

        registry = default_model_registry()
        arg = arg.strip()
        current = getattr(getattr(self._agent, "llm", None), "_model", Config.MODEL)
        if not arg:
            table = Table(title="Models", box=box.ROUNDED)
            table.add_column("ID", style="bold cyan")
            table.add_column("Provider")
            table.add_column("TPM", justify="right")
            table.add_column("RPS", justify="right")
            table.add_column("", style="green")
            for spec in registry.all():
                rl = spec.rate_limit
                tpm = f"{rl.tokens_per_minute:,}" if rl.tokens_per_minute else "—"
                rps = f"{rl.requests_per_second}" if rl.requests_per_second else "—"
                active = "● active" if current in (spec.model_name, spec.id) else ""
                table.add_row(spec.id, spec.provider, tpm, rps, active)
            console.print(table)
            console.print(
                f"[dim]Active model: [bold]{current}[/bold]. Switch with "
                f"[cyan]/model <id>[/cyan] (bare name or provider/name).[/dim]"
            )
            return
        spec = registry.get(arg) or next(
            (s for s in registry.all() if s.model_name == arg), None
        )
        model_name = spec.model_name if spec else arg
        llm = getattr(self._agent, "llm", None)
        if llm is None or not hasattr(llm, "_model"):
            console.print("[red]Active agent has no switchable model.[/red]")
            return
        if spec and spec.provider != Config.PROVIDER:
            console.print(
                f"[yellow]Note: {spec.id} is a {spec.provider} model but the active "
                f"provider is {Config.PROVIDER}. Setting the model name only; ensure "
                f"the active provider/key serves it.[/yellow]"
            )
        llm._model = model_name
        Config.MODEL = model_name
        console.print(f"[green]Model → [bold]{model_name}[/bold][/green]")

    def _host_controller(self):
        from decode.governance import GovernanceGate, ScopePolicy
        from decode.runtime import ExecutionCoordinator, HostController

        if self._host_ctl is None:
            self._host_gate = GovernanceGate(ScopePolicy(allow_all=True), mode=self._perm_mode)
            coord = ExecutionCoordinator(self._host_gate, approval_callback=self._host_approval)
            self._host_ctl = HostController(coord, self._fs_scope, self._cmd_policy)
        else:
            self._host_gate.set_mode(self._perm_mode)
            self._host_ctl.set_scope(self._fs_scope, self._cmd_policy)
        return self._host_ctl

    def _host_approval(self, request):
        return Confirm.ask(f"  Approve {request.action} ({request.risk.value})?", default=False)

    def _handle_mode(self, arg):
        if not arg:
            console.print(f"Permission mode: [bold]{self._perm_mode.value}[/bold]  [dim](plan | ask | auto)[/dim]")
            return
        try:
            self._perm_mode = PermissionMode(arg.lower())
        except ValueError:
            console.print("[yellow]Usage: /mode plan|ask|auto[/yellow]")
            return
        console.print(f"[green]Permission mode → [bold]{self._perm_mode.value}[/bold][/green]")

    def _handle_fsscope(self, arg):
        parts = arg.split()
        if not parts:
            console.print("[dim]Read scope defaults to the working directory. Usage: /fsscope <read_root> [write_root][/dim]")
            return
        write_roots = [parts[1]] if len(parts) > 1 else []
        self._fs_scope = FilesystemScope(read_roots=[parts[0]] + write_roots, write_roots=write_roots)
        extra = f", write: {parts[1]}" if write_roots else ""
        console.print(f"[green]Filesystem scope set (read: {parts[0]}{extra})[/green]")

    async def _handle_host(self, capability, params):
        result = await self._host_controller().run(capability, params)
        self._render_host(capability, result)

    async def _handle_agent(self, goal):
        if not goal:
            console.print("[yellow]Usage: /agent <goal>[/yellow]")
            return
        # No spinner here: tool calls may prompt for approval, which conflicts
        # with a live spinner. The loop respects the current /mode. Steps and the
        # model's first-person reasoning are streamed live via on_step.
        console.print(f"[dim]Agent working on: {goal}  (mode: {self._perm_mode.value})[/dim]\n")

        def on_step(event):
            phase = event.get("phase")
            thought = (event.get("thought") or "").strip()
            if phase in ("call", "final") and thought:
                console.print(f"[magenta]🧠 {thought}[/magenta]")
            if phase == "call":
                params = json.dumps(event.get("params", {}))[:80]
                console.print(f"  [dim]▶ running[/dim] [cyan]{event.get('tool')}[/cyan] [dim]{params}[/dim]")
            elif phase == "result":
                obs = event.get("observation", {}) or {}
                icon = "[green]✓[/green]" if obs.get("success") else "[red]✗[/red]"
                console.print(f"  {icon} [dim]{str(obs.get('summary', ''))[:110]}[/dim]")

        result = await self._agent.run_tool_loop(
            goal,
            filesystem_scope=self._fs_scope,
            command_policy=self._cmd_policy,
            permission_mode=self._perm_mode,
            approval_callback=self._host_approval,
            on_step=on_step,
        )
        console.print(f"\n[bold]{result.get('final', '')}[/bold]\n")

    def _render_host(self, capability, result):
        from decode.runtime.coordinator import ExecutionStatus

        if result.status != ExecutionStatus.SUCCESS:
            reason = result.error or (result.value.error if result.value else "") or result.status.value
            console.print(f"[bold red]{capability} {result.status.value}:[/bold red] {reason}")
            return
        data = result.value.normalized if result.value else {}
        console.print(f"[bold green]✓[/bold green] [bold]{capability}[/bold]")
        self._render_json(data)

    def _handle_knowledge(self, query):
        from decode.knowledge import KnowledgeRetriever
        hits = KnowledgeRetriever().relevant_for_goal(query)
        if not hits:
            console.print(f"[yellow]No knowledge matched '{query}'.[/yellow]")
            return
        table = Table(title=f"Knowledge: '{query}'", box=box.ROUNDED)
        table.add_column("Type", style="cyan")
        table.add_column("Name", style="bold")
        for n in hits:
            table.add_row(n.get("type", ""), n.get("name", ""))
        console.print(table)

    def _missing_required_target(self, action, params):
        """True when a proposed skill needs a target but none was supplied."""
        skill = self._registry.get(action)
        spec = getattr(skill, "spec", None) if skill else None
        if spec is None:
            return False
        try:
            requires = spec.requires_scoped_target()
        except Exception:
            requires = getattr(spec, "target_required", False)
        params = params or {}
        has_target = bool(params.get("target") or params.get("url") or params.get("domain"))
        return bool(requires) and not has_target

    async def _chat_loop(self, text):
        # The bare prompt IS the universal agent: natural-language goals and plain
        # questions both go through the governed tool-use loop, which discovers
        # installed tools (list_tools) and drives them via shell_command. There is
        # no single-skill proposer anymore.
        ip_match = re.search(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', text)
        if ip_match and not self._current_target:
            detected = ip_match.group(1)
            self._current_target = detected
            console.print(f"[dim]Detected target: {detected}[/dim]")
        if not self._session_active and self._current_target:
            self._handle_start(f"/start {self._current_target}")
        await self._handle_agent(text)

    async def _execute_tool(self, action, params=None):
        start = time.time()
        try:
            with console.status(f"[cyan]Running [bold]{action}[/bold]…[/cyan]", spinner="dots"):
                execution = await self._agent.execute_registered_skill(
                    action,
                    params or {},
                    human_approved=True,
                )
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            return
        if not execution.success:
            category = (
                execution.error_category.value
                if execution.error_category
                else "execution_failure"
            )
            console.print(
                f"[bold red]Blocked:[/bold red] {category}: {execution.error}"
            )
            return
        result = execution.value
        safe_result = redact_sensitive(result)
        duration = time.time() - start
        console.print(f"[bold green]✓[/bold green] [bold]{action}[/bold] completed [dim]({duration:.1f}s)[/dim]")
        self._render_result(action, safe_result)
        if self._session_active and self._tracker and action in self._finding_type_map:
            cat, sev = self._finding_type_map[action]
            finding = TargetFinding(title=f"{action} results", description=str(result)[:300], severity=sev, category=cat)
            self._tracker.record_finding(finding)
            self._store.add_evidence(
                self._tracker.session_id, type="command_output", label=action,
                data={"result": str(safe_result)[:1000]}, source=action,
            )
        with console.status("[white]Analyzing results…[/white]", spinner="dots"):
            follow_up = await self._agent.chat(
                f"I've executed the tool. Here is the result (truncated): {str(safe_result)[:4000]}",
                self._domain,
            )
        if follow_up:
            msg = follow_up.get("message", "")
            decision_summary = follow_up.get("decision_summary", "")
            if decision_summary:
                console.print(f"\n[blue]Decision:[/blue] {decision_summary}")
            if msg:
                console.print(Markdown(msg))
        console.print("")

    async def _execute_command(self, command):
        console.print(f"\n[bold cyan]▶[/bold cyan] $ [bold]{command}[/bold]")
        start = time.time()
        try:
            result = await self._agent.execute_command(command)
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            return
        duration = time.time() - start

        if result.success:
            console.print(f"[bold green]✓[/bold green] Command succeeded [dim]({duration:.1f}s)[/dim]")
            if result.stdout:
                console.print(Markdown(f"```\n{result.stdout[:2000]}\n```"))
            console.print("\n[bold white]Analyzing results...[/bold white]")
            follow_up = await self._agent.chat(
                f"The command completed successfully.\nSTDOUT: {result.stdout[:2000]}",
                self._domain,
            )
        else:
            console.print(f"[bold red]✗[/bold red] Command failed [dim]({duration:.1f}s)[/dim]")
            if result.timed_out:
                console.print(f"[bold red]Timed out after {duration:.1f}s[/bold red]")
            elif result.error:
                console.print(f"[bold red]{result.error}[/bold red]")
            else:
                console.print(f"[bold red]Exit code: {result.exit_code}[/bold red]")
            if result.stdout:
                console.print(f"[dim]STDOUT:[/dim] {result.stdout[:500]}")
            if result.stderr:
                console.print(f"[dim]STDERR:[/dim] {result.stderr[:500]}")
            console.print("\n[bold yellow]Analyzing error...[/bold yellow]")
            follow_up = await self._agent.chat(
                f"The command failed.\nSTDOUT: {result.stdout[:1000]}\nSTDERR: {result.stderr[:500]}\nExit code: {result.exit_code}\nPlease diagnose and suggest a fix.",
                self._domain,
            )

        if follow_up:
            msg = follow_up.get("message", "")
            decision_summary = follow_up.get("decision_summary", "")
            action = follow_up.get("action")
            command = follow_up.get("command")
            if decision_summary:
                console.print(f"\n[blue]Decision:[/blue] {decision_summary}")
            if msg:
                console.print(Markdown(msg))
            if command:
                console.print(
                    "[bold red]Blocked:[/bold red] model-generated raw commands are not "
                    "part of the governed capability pipeline."
                )
            elif action:
                params = follow_up.get("params", {})
                if self._missing_required_target(action, params):
                    console.print(
                        "[yellow]This action needs a target.[/yellow] "
                        "[dim]Reply with an IP, hostname, URL, or CIDR.[/dim]"
                    )
                else:
                    metadata = follow_up.get("plugin_metadata", {})
                    risk = metadata.get("risk_level", "UNKNOWN")
                    console.print(f"\n[b]Proposal:[/b] [bold]{action}[/bold]")
                    if params:
                        console.print(
                            f"[dim]  Params: {json.dumps(redact_sensitive(params))}[/dim]"
                        )
                    console.print()
                    self._pending_action = {"type": "skill", "action": action, "params": params, "risk": risk}
                    console.print("[b]Approve?[/b] (y/n)")
        console.print("")

    def _save_session(self):
        if not self._tracker:
            return
        hp = Path(f"./data/sessions/{self._tracker.session_id}.json")
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(json.dumps(self._conversation_history, indent=2), encoding="utf-8")
        self._store.close_session(self._tracker.session_id)
