import asyncio
import json
import sys

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table

from ..bootstrap.engine import BootstrapEngine
from ..observability.audit import AuditLayer
from ..observability.feedback import FeedbackStore
from ..observability.logging_service import LoggingService
from ..persistence import create_store
from ..tui import AgentREPL
from .config import Config

app = typer.Typer()
console = Console()
_store = create_store()


def _configure_output_encoding() -> None:
    if sys.platform != "win32":
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def display_banner():
    banner = """
    [bold red]     _                    _       [/bold red]
    [bold red]  __| | ___  ___ ___   __| | ___  [/bold red]
    [bold yellow] / _` |/ _ \\/ __/ _ \\ / _` |/ _ \\ [/bold yellow]
    [bold white]| (_| |  __/ (_| (_) | (_| |  __/ [/bold white]
    [bold white] \\__,_|\\___|\\___\\___/ \\__,_|\\___| [/bold white]
    """
    console.print(
        Panel(
            banner,
            subtitle="[bold cyan]v2.0.0 - Governed Universal Agent[/bold cyan]",
            border_style="bold blue",
        )
    )


_bootstrap = BootstrapEngine()
_logger = LoggingService(Config.LOGS_PATH)
_audit = AuditLayer(Config.AUDIT_PATH)
_feedback = FeedbackStore(Config.FEEDBACK_PATH)


def _apply_plugin_playbook_dirs() -> None:
    """Add enabled plugins' skill directories to DECODE_PLAYBOOKS_DIR so the
    SkillRegistry (built when the agent starts) discovers plugin playbooks."""
    import os

    try:
        from ..extensions import ExtensionManager

        dirs = [str(d) for d in ExtensionManager().playbook_dirs()]
    except Exception:
        return
    if not dirs:
        return
    existing = os.environ.get("DECODE_PLAYBOOKS_DIR", "")
    parts = [p for p in existing.split(os.pathsep) if p] + dirs
    os.environ["DECODE_PLAYBOOKS_DIR"] = os.pathsep.join(dict.fromkeys(parts))


def start_repl(
    domain: str = "redteam",
    provider: str | None = None,
    resume: str | None = None,
    continue_last: bool = False,
) -> None:
    _configure_output_encoding()

    display_banner()

    _apply_plugin_playbook_dirs()

    try:
        from ..universal_agent import UniversalAgent

        agent = UniversalAgent(provider=provider or Config.PROVIDER)
    except ImportError as e:
        console.print(f"[bold red]Dependency Error:[/bold red] {e!s}")
        console.print("[yellow]Run 'pip install -r requirements.txt'[/yellow]")
        return

    repl = AgentREPL(
        agent=agent, domain=domain, resume=resume, continue_last=continue_last
    )
    repl.run()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    domain: str = typer.Option("redteam", "--domain", "-d", help="Starting domain"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="LLM provider"),
    setup: bool = typer.Option(False, "--setup", help="Run setup"),
    doctor: bool = typer.Option(False, "--doctor", help="Check dependencies"),
    resume: str | None = typer.Option(
        None, "--resume", "-r", help="Resume a saved session by id"
    ),
    continue_last: bool = typer.Option(
        False, "--continue", "-c", help="Continue the most recent session"
    ),
) -> None:
    """Decode v2 — Governed Universal Agent"""
    _configure_output_encoding()
    Config.reload()
    selected_provider = provider or Config.PROVIDER
    if ctx.invoked_subcommand is None:
        if not setup and not Config.has_provider_credentials(selected_provider):
            key_name = Config.provider_key_name(selected_provider)
            console.print(f"[dim yellow]No {key_name} found in .env[/dim yellow]")
            setup = True
    if setup:
        run_setup()
        return
    if doctor:
        run_doctor()
        return
    if ctx.invoked_subcommand is None:
        Config.ensure_dirs()
        _bootstrap.generate_report()
        start_repl(
            domain, selected_provider, resume=resume, continue_last=continue_last
        )


@app.command()
def doctor():
    """Run system health diagnostics"""
    Config.ensure_dirs()
    run_doctor()


@app.command()
def version():
    """Show the installed De-code version"""
    from .. import __version__

    console.print(f"De-code {__version__}")


@app.command()
def providers(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON for scripting"),
):
    """List execution providers and their health status"""
    from ..execution import available_provider_names, create_executor

    async def _health(name):
        provider = create_executor(name)
        try:
            ok = await provider.check_health()
        except Exception:
            ok = False
        return provider.name, ok

    rows = []
    for key in available_provider_names():
        name, ok = asyncio.run(_health(key))
        rows.append({"provider": key, "name": name, "available": ok})

    if json_output:
        print(json.dumps({"active": Config.EXECUTOR, "providers": rows}, indent=2))
        return

    table = Table(title="Execution Providers", box=box.ROUNDED)
    table.add_column("Provider", style="cyan")
    table.add_column("Name", style="dim")
    table.add_column("Health", style="bold")
    for row in rows:
        status = (
            "[green]available[/green]"
            if row["available"]
            else "[yellow]unavailable[/yellow]"
        )
        table.add_row(row["provider"], row["name"], status)
    console.print(table)
    console.print(
        f"[dim]Active provider: [bold]{Config.EXECUTOR}[/bold] (set DECODE_EXECUTOR to change)[/dim]"
    )


@app.command()
def models(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON for scripting"),
) -> None:
    """Fetch every model in the live OpenRouter catalogue."""
    from ..models import OpenRouterCatalogError, fetch_openrouter_catalog

    try:
        result = fetch_openrouter_catalog(Config.OPENROUTER_API_KEY)
    except (OpenRouterCatalogError, ValueError) as exc:
        if json_output:
            print(json.dumps({"error": str(exc), "models": []}, indent=2))
        else:
            console.print(f"[red]Could not fetch OpenRouter models: {exc}[/red]")
        raise typer.Exit(1) from None

    if json_output:
        print(
            json.dumps(
                {
                    "source": "openrouter-live",
                    "total_count": result.total_count,
                    "skipped": result.skipped,
                    "models": [spec.model_dump(mode="json") for spec in result.models],
                },
                indent=2,
            )
        )
        return

    table = Table(title="OpenRouter Models", box=box.ROUNDED)
    table.add_column("ID", style="bold cyan")
    table.add_column("Context", justify="right")
    table.add_column("Input $/M", justify="right")
    table.add_column("Output $/M", justify="right")
    table.add_column("Capabilities", style="dim")
    for spec in result.models:
        unavailable = spec.cost.pricing_version == "openrouter-live-unavailable"
        table.add_row(
            spec.model_name,
            f"{spec.context_limit:,}",
            "—" if unavailable else f"{spec.cost.input_per_mtok:g}",
            "—" if unavailable else f"{spec.cost.output_per_mtok:g}",
            ", ".join(spec.capabilities) or "—",
        )
    console.print(table)
    suffix = f" ({result.skipped} invalid records skipped)" if result.skipped else ""
    console.print(f"[dim]{len(result.models)} OpenRouter models{suffix}.[/dim]")


@app.command()
def tools(
    query: str = typer.Argument("", help="Filter installed tools by name substring"),
    limit: int = typer.Option(400, "--limit", "-n", help="Max tools to list"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON for scripting"),
):
    """List command-line tools installed on this host (from $PATH).

    Mirrors the governed ``list_tools`` capability the agent uses to discover what
    it can run; there is no hardcoded tool catalog.
    """
    from ..hostcontrol import operations as ops

    result = ops.list_tools(query=query, limit=limit)
    if json_output:
        print(json.dumps(result, indent=2))
        return
    console.print(
        f"[green]Installed tools on $PATH:[/green] {result['count']}"
        + (f"  [dim](filter: '{query}')[/dim]" if query else "")
        + ("  [yellow](truncated)[/yellow]" if result["truncated"] else "")
    )
    table = Table(title="Installed CLI tools", box=box.ROUNDED)
    table.add_column("Tool", style="bold cyan")
    table.add_column("Path", style="dim")
    for entry in result["tools"]:
        table.add_row(entry["name"], entry["path"])
    console.print(table)


@app.command()
def sessions(
    limit: int = typer.Option(20, "--limit", "-n", help="Max sessions to list"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON for scripting"),
):
    """List recent sessions (the non-interactive equivalent of /sessions)."""
    from ..persistence.manager import SessionManager

    rows = SessionManager(_store).list(limit=limit)
    if json_output:
        print(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        console.print(
            "[dim]No sessions yet. Run `decode` and type a task to begin one.[/dim]"
        )
        return
    table = Table(title="Sessions", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Status")
    table.add_column("Created")
    table.add_column("Goal")
    for s in rows:
        table.add_row(
            s.get("id", ""),
            s.get("status", ""),
            (s.get("created_at", "") or "")[:19],
            (s.get("goal", "") or "")[:48],
        )
    console.print(table)


@app.command()
def knowledge(
    query: str = typer.Argument(
        ..., help="Search the knowledge base (techniques, threats, mitigations)"
    ),
):
    """Search the knowledge base for relevant techniques and references"""
    Config.ensure_dirs()
    from ..knowledge import KnowledgeRetriever

    retriever = KnowledgeRetriever()
    hits = retriever.relevant_for_goal(query)
    if not hits:
        console.print(f"[yellow]No knowledge matched '{query}'.[/yellow]")
        return
    table = Table(title=f"Knowledge: '{query}'", box=box.ROUNDED)
    table.add_column("Type", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Source", style="dim")
    for n in hits:
        table.add_row(n.get("type", ""), n.get("name", ""), n.get("source", ""))
    console.print(table)


@app.command()
def bootstrap(
    update: bool = typer.Option(False, "--update", "-u", help="Run system update"),
):
    """Run bootstrap sequence at first startup"""
    Config.ensure_dirs()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task("[yellow]Bootstrapping system...", total=None)
        result = _bootstrap.run(do_update=update)
    distro = result["distro"]
    report = result["bootstrap_report"]
    console.print(
        f"[green]System:[/green] {distro.get('id', 'unknown')} {distro.get('version_id', '')}"
    )
    console.print(f"[green]Python:[/green] {report['python']}")
    console.print(f"[green]Docker:[/green] {report['docker']}")
    console.print(f"[green]Nmap:[/green] {report['nmap']}")
    console.print("[green]Report saved:[/green] data/bootstrap_report.json")


mcp_app = typer.Typer(
    help="Manage external MCP providers (add/list/…) and run De-code's own "
    "MCP/HTTP server (start/stop/status/config)"
)
app.add_typer(mcp_app, name="mcp")


def _mcp_manager():
    from ..extensions import ExtensionManager

    return ExtensionManager().mcp


def _parse_scope(scope: str):
    from ..extensions import Scope

    try:
        return Scope(scope)
    except ValueError:
        console.print(
            f"[red]Unknown scope '{scope}'. Use user, project, or system.[/red]"
        )
        raise typer.Exit(1) from None


@mcp_app.command("add")
def mcp_add(
    name: str = typer.Argument(..., help="Server name, e.g. mongodb"),
    command_parts: list[str] = typer.Argument(
        None, help="Launcher after `--`, e.g. -- npx -y mongodb-mcp-server"
    ),
    transport: str = typer.Option("stdio", "--transport", help="stdio | http"),
    url: str = typer.Option("", "--url", help="Endpoint for http/sse transports"),
    risk: str = typer.Option(
        "write", "--risk", help="Declared risk: read | write | destructive"
    ),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Register an MCP server, e.g. `decode mcp add mongodb -- npx -y mongodb-mcp-server`."""
    from ..extensions.mcp_manager import MCPServerSpec

    parts = command_parts or []
    spec = MCPServerSpec(
        name=name,
        transport=transport,
        url=url,
        risk=risk,
        command=parts[0] if parts else "",
        args=parts[1:],
    )
    try:
        _mcp_manager().add(spec, scope=_parse_scope(scope))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]Added MCP server '{name}' ({scope} scope).[/green]")


@mcp_app.command("list")
def mcp_list():
    """List configured MCP servers."""
    servers = _mcp_manager().list_servers()
    if not servers:
        console.print(
            "[dim]No MCP servers configured. Add one with `decode mcp add`.[/dim]"
        )
        return
    table = Table(title="MCP Servers", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Transport")
    table.add_column("Launcher")
    table.add_column("Risk")
    table.add_column("Enabled", style="bold")
    for name, spec in sorted(servers.items()):
        launcher = spec.url or " ".join([spec.command, *spec.args]).strip()
        table.add_row(
            name, spec.transport, launcher, spec.risk, "yes" if spec.enabled else "no"
        )
    console.print(table)


@mcp_app.command("remove")
def mcp_remove(
    name: str = typer.Argument(..., help="Server name"),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Remove a configured MCP server."""
    removed = _mcp_manager().remove(name, scope=_parse_scope(scope))
    if removed:
        console.print(f"[green]Removed MCP server '{name}' ({scope} scope).[/green]")
    else:
        console.print(f"[yellow]No MCP server '{name}' in {scope} scope.[/yellow]")


@mcp_app.command("enable")
def mcp_enable(
    name: str = typer.Argument(...),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Enable a configured MCP server."""
    ok = _mcp_manager().set_enabled(name, True, scope=_parse_scope(scope))
    console.print(
        f"[green]Enabled '{name}'.[/green]"
        if ok
        else f"[yellow]No MCP server '{name}'.[/yellow]"
    )


@mcp_app.command("disable")
def mcp_disable(
    name: str = typer.Argument(...),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Disable a configured MCP server (kept, but not started or exposed)."""
    ok = _mcp_manager().set_enabled(name, False, scope=_parse_scope(scope))
    console.print(
        f"[green]Disabled '{name}'.[/green]"
        if ok
        else f"[yellow]No MCP server '{name}'.[/yellow]"
    )


@mcp_app.command("start")
def mcp_start(
    port: int = typer.Option(8765, "--port", help="Port to bind (http transport)"),
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Bind address (local-only by default)"
    ),
    transport: str = typer.Option(
        "http", "--transport", help="http (localhost REST) | stdio (native MCP)"
    ),
    mode: str = typer.Option(
        "ask", "--mode", help="Governance mode: plan | ask | auto"
    ),
    read_root: list[str] = typer.Option(
        None, "--read-root", help="Filesystem read-scope root (repeatable)"
    ),
    write_root: list[str] = typer.Option(
        None, "--write-root", help="Filesystem write-scope root (repeatable)"
    ),
):
    """Start De-code's MCP server: localhost HTTP (default) or native MCP stdio."""
    from pathlib import Path

    from ..hostcontrol import PermissionMode
    from ..mcp import DecodeMCPServer, MCPServerConfig

    if transport not in ("http", "stdio"):
        console.print("[red]Invalid --transport. Use http or stdio.[/red]")
        raise typer.Exit(1) from None

    Config.ensure_dirs()
    try:
        perm = PermissionMode(mode.lower())
    except ValueError:
        console.print("[red]Invalid --mode. Use plan, ask, or auto.[/red]")
        raise typer.Exit(1) from None

    config = MCPServerConfig(
        host=host,
        port=port,
        mode=perm,
        read_roots=list(read_root) if read_root else [str(Path.cwd())],
        write_roots=list(write_root) if write_root else [],
    )
    server = DecodeMCPServer(config)

    if transport == "stdio":
        # The stdio transport speaks the MCP protocol on stdout, so emit the
        # startup note on stderr to avoid corrupting the stream.
        from ..mcp.stdio import run_stdio

        print(
            f"De-code MCP stdio server (mode={perm.value}, "
            f"tools={len(server.list_tools())}). Connect an MCP client to this "
            "process's stdio.",
            file=sys.stderr,
        )
        try:
            asyncio.run(run_stdio(server))
        except RuntimeError as exc:
            from rich.markup import escape

            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(1) from None
        except KeyboardInterrupt:
            pass
        return

    from ..mcp.transport import run_http

    if not config.is_local:
        console.print(
            f"[yellow]Warning: binding to a non-local address ({host}); "
            "the server has no authentication yet.[/yellow]"
        )
    console.print(
        f"[green]De-code MCP server[/green] on [cyan]{config.url}[/cyan]  "
        f"mode=[bold]{perm.value}[/bold]  tools={len(server.list_tools())}"
    )
    import importlib.util

    mcp_note = (
        "  Native MCP: POST /mcp"
        if importlib.util.find_spec("mcp")
        else "  (install decode[mcp] for a native /mcp endpoint)"
    )
    console.print(
        "[dim]Endpoints: GET /health, GET /tools, POST /tools/{name}." + mcp_note + "  "
        "Press Ctrl+C to stop.[/dim]"
    )
    try:
        run_http(server, config)
    except RuntimeError as exc:
        from rich.markup import escape

        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        console.print("\n[dim]MCP server stopped.[/dim]")


@mcp_app.command("status")
def mcp_status(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON for scripting"),
):
    """Show the local MCP server's recorded endpoint and ping its health."""
    from ..mcp.transport import read_state

    state = read_state()
    health = None
    if state:
        url = state.get("url", "")
        try:
            import requests

            health = requests.get(f"{url}/health", timeout=2).json()
        except Exception as exc:
            health = {"error": str(exc)}

    if json_output:
        print(
            json.dumps(
                {"running": bool(state), "state": state, "health": health}, indent=2
            )
        )
        return

    if not state:
        console.print(
            "[dim]No MCP server state found. Start one with `decode mcp start`.[/dim]"
        )
        return
    console.print(
        f"[cyan]Endpoint:[/cyan] {state.get('url', '')}   "
        f"[cyan]pid:[/cyan] {state.get('pid')}   [cyan]mode:[/cyan] {state.get('mode')}"
    )
    if isinstance(health, dict) and "error" not in health:
        console.print(f"[green]Health:[/green] {health}")
    else:
        err = health.get("error") if isinstance(health, dict) else health
        console.print(
            f"[yellow]Health check failed (server may be stopped): {err}[/yellow]"
        )


@mcp_app.command("stop")
def mcp_stop():
    """Stop the local MCP server recorded by `decode mcp start`."""
    import os
    import signal

    from ..mcp.transport import clear_state, read_state

    state = read_state()
    if not state or not state.get("pid"):
        console.print("[dim]No running MCP server recorded.[/dim]")
        return
    pid = int(state["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent stop signal to MCP server (pid {pid}).[/green]")
    except ProcessLookupError:
        console.print(
            "[yellow]Recorded process not found; clearing stale state.[/yellow]"
        )
    except OSError as exc:
        console.print(f"[red]Could not stop server: {exc}[/red]")
        return
    clear_state()


@mcp_app.command("config")
def mcp_config():
    """Show the default server binding and the governed tools it would expose."""
    from ..mcp import DecodeMCPServer, MCPServerConfig

    cfg = MCPServerConfig()
    server = DecodeMCPServer(cfg)
    console.print(
        f"[bold]Default bind:[/bold] {cfg.url}   mode={cfg.mode.value}   "
        f"read_roots={cfg.read_roots}"
    )
    table = Table(title="Exposed governed tools", box=box.ROUNDED)
    table.add_column("Tool", style="cyan")
    table.add_column("Risk")
    table.add_column("Description")
    for tool in server.list_tools():
        table.add_row(tool["name"], tool["risk"], tool["description"])
    console.print(table)


plugin_app = typer.Typer(help="Manage plugin packages (declarative capability bundles)")
app.add_typer(plugin_app, name="plugin")


def _plugin_manager():
    from ..extensions import ExtensionManager

    return ExtensionManager().plugins


@plugin_app.command("install")
def plugin_install(
    source: str = typer.Argument(..., help="Path to a plugin package directory"),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Install a plugin package from a local directory (verifies its manifest)."""
    from pathlib import Path as _Path

    try:
        manifest = _plugin_manager().install(_Path(source), scope=_parse_scope(scope))
    except (ValueError, OSError) as exc:
        console.print(f"[red]Install failed: {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(
        f"[green]Installed plugin '{manifest.name}' v{manifest.version} ({scope} scope).[/green]"
    )


@plugin_app.command("list")
def plugin_list():
    """List installed plugins."""
    plugins = _plugin_manager().list_plugins()
    if not plugins:
        console.print(
            "[dim]No plugins installed. Install one with `decode plugin install`.[/dim]"
        )
        return
    table = Table(title="Plugins", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Version")
    table.add_column("Description")
    table.add_column("Enabled", style="bold")
    for name, record in sorted(plugins.items()):
        table.add_row(
            name, record.version, record.description, "yes" if record.enabled else "no"
        )
    console.print(table)


@plugin_app.command("remove")
def plugin_remove(
    name: str = typer.Argument(...),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Remove an installed plugin (and the MCP servers it registered)."""
    removed = _plugin_manager().remove(name, scope=_parse_scope(scope))
    console.print(
        f"[green]Removed plugin '{name}'.[/green]"
        if removed
        else f"[yellow]No plugin '{name}' in {scope} scope.[/yellow]"
    )


@plugin_app.command("enable")
def plugin_enable(
    name: str = typer.Argument(...),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Enable an installed plugin."""
    ok = _plugin_manager().set_enabled(name, True, scope=_parse_scope(scope))
    console.print(
        f"[green]Enabled '{name}'.[/green]"
        if ok
        else f"[yellow]No plugin '{name}'.[/yellow]"
    )


@plugin_app.command("disable")
def plugin_disable(
    name: str = typer.Argument(...),
    scope: str = typer.Option("user", "--scope", help="user | project | system"),
):
    """Disable an installed plugin (kept, but its components are not exposed)."""
    ok = _plugin_manager().set_enabled(name, False, scope=_parse_scope(scope))
    console.print(
        f"[green]Disabled '{name}'.[/green]"
        if ok
        else f"[yellow]No plugin '{name}'.[/yellow]"
    )


def run_setup() -> None:
    console.print("[bold yellow]Setup Decode[/bold yellow]")
    provider = Prompt.ask(
        "LLM provider",
        choices=["openrouter", "openai", "anthropic"],
        default=Config.PROVIDER,
    )
    key_name = Config.provider_key_name(provider)
    api_key = Prompt.ask(f"Enter your {provider} API key", password=True)
    model_settings = {
        "openrouter": ("DECODE_MODEL", Config.DEFAULT_MODEL),
        "openai": ("OPENAI_MODEL", "gpt-4o"),
        "anthropic": ("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
    }
    model_name, model_default = model_settings[provider]
    model = Prompt.ask("Model", default=model_default)

    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"DECODE_PROVIDER={provider}\n")
        f.write(f"{key_name}={api_key}\n")
        f.write(f"{model_name}={model}\n")

    console.print("[green][OK] .env created! Run 'decode' to start.[/green]")


def run_doctor():
    console.print("[bold blue]Decode System Health[/bold blue]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task("[yellow]Checking environment...", total=None)
        _bootstrap.generate_report()
        from ..hostcontrol import operations as ops

        installed = ops.list_tools(limit=5000)

    checks = _bootstrap.check_security()
    table = Table(title="Core Dependencies", box=box.ROUNDED)
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="bold")
    all_ok = True
    for c in checks:
        ok = c.status != "missing"
        if not ok:
            all_ok = False
        icon = "[green]OK[/green]" if ok else "[red]X[/red]"
        status_str = c.status if ok else "[red]MISSING[/red]"
        table.add_row(f"{icon} {c.check}", status_str)
    console.print(table)

    console.print(
        f"\n[bold]Installed CLI tools on $PATH:[/bold] {installed['count']}"
        + ("+ (truncated)" if installed["truncated"] else "")
    )
    console.print(
        "[dim]The agent discovers and runs these on demand via the governed "
        "shell_command capability; there is no hardcoded tool catalog.[/dim]"
    )

    api_ok = Config.has_provider_credentials()
    key_name = Config.provider_key_name()
    api_icon = "[green]OK[/green]" if api_ok else "[red]X[/red]"
    api_status = "[green]Configured[/green]" if api_ok else "[red]Missing[/red]"
    console.print(f"\n{api_icon} {Config.PROVIDER} ({key_name}): {api_status}")

    if not all_ok or not api_ok:
        console.print("\n[bold yellow]Issues found:[/bold yellow]")
        if not api_ok:
            console.print(f"  - Set {key_name} in .env or choose another provider")
        missing_tools = [c.check for c in checks if c.status == "missing"]
        if missing_tools:
            console.print(f"  - Missing system tools: {', '.join(missing_tools)}")


if __name__ == "__main__":
    app()
