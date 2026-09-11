"""HTTP transport for the De-code MCP server, plus run-state bookkeeping.

FastAPI and uvicorn are optional (``pip install 'decode[server]'``) and imported
lazily so importing this module never requires a web stack. ``run_http`` records
the live endpoint/pid to a state file so ``decode mcp status`` and ``stop`` can
find it, and clears it on shutdown.
"""

import json
import os
from typing import Any

from .config import MCPServerConfig, state_dir, state_file
from .server import DecodeMCPServer

_SERVER_MISSING = (
    "The De-code HTTP server needs FastAPI and uvicorn. "
    "Install them with: pip install 'decode[server]'"
)


def build_fastapi_app(server: DecodeMCPServer):
    """Build the FastAPI app.

    Always serves the convenience REST API (/health, /tools, POST /tools/{name}).
    When the optional ``mcp`` SDK is installed it also mounts a native MCP
    streamable-HTTP endpoint at ``/mcp`` so standard MCP clients can connect over
    one HTTP endpoint.
    """
    try:
        from fastapi import FastAPI, Request
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(_SERVER_MISSING) from exc

    from .. import __version__

    mcp_mount = _build_mcp_asgi(server)  # (handler, lifespan) or None
    lifespan = mcp_mount[1] if mcp_mount else None
    app = FastAPI(title="De-code MCP Server", version=__version__, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, Any]:
        info = server.health()
        info["mcp_endpoint"] = "/mcp" if mcp_mount else None
        return info

    @app.get("/tools")
    def tools() -> dict[str, Any]:
        return {"tools": server.list_tools()}

    @app.post("/tools/{name}")
    async def call_tool(name: str, request: Request) -> dict[str, Any]:
        arguments = await _extract_arguments(request)
        return await server.call_tool(name, arguments)

    if mcp_mount:
        app.mount("/mcp", app=mcp_mount[0])

    return app


def _build_mcp_asgi(server: DecodeMCPServer):
    """Build the native MCP streamable-HTTP ASGI handler + lifespan.

    Returns ``(handler, lifespan)`` when the ``mcp`` SDK is available, else
    ``None`` (the REST API still works without it).
    """
    try:
        import contextlib

        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    except ImportError:
        return None

    from .stdio import build_mcp_server

    manager = StreamableHTTPSessionManager(app=build_mcp_server(server))

    async def handle(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    return handle, lifespan


async def _extract_arguments(request) -> dict[str, Any]:
    """Read tool arguments from the request body.

    Accepts either the wrapped form ``{"arguments": {...}}`` or a bare arguments
    object ``{...}``; an empty or invalid body means no arguments.
    """
    try:
        payload = await request.json()
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("arguments")
    if isinstance(inner, dict):
        return inner
    return payload


def run_http(server: DecodeMCPServer, config: MCPServerConfig) -> None:
    """Run the blocking HTTP server, recording run-state for status/stop."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(_SERVER_MISSING) from exc

    app = build_fastapi_app(server)
    write_state(config)
    try:
        uvicorn.run(app, host=config.host, port=config.port, log_level="warning")
    finally:
        clear_state()


# -- run-state file --------------------------------------------------------
def write_state(config: MCPServerConfig) -> None:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "url": config.url, **config.to_dict()}
    state_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_state() -> dict[str, Any] | None:
    path = state_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def clear_state() -> None:
    try:
        state_file().unlink()
    except OSError:
        pass
