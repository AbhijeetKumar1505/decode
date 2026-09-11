"""De-code MCP / localhost HTTP server.

Exposes the existing governed host capabilities (files, search, processes,
services, shell commands, sessions) to MCP-compatible and HTTP clients. Every
invocation still routes through the ``ExecutionCoordinator`` and its governance
gate, so scope, approval, audit, and evidence are unchanged — the server is a
transport, not a new execution path.

The core (``DecodeMCPServer`` + ``MCPServerConfig``) is pure-Python and has no
web dependencies; the HTTP transport (FastAPI/uvicorn) lives in
``transport`` and is imported lazily so the core stays importable without the
optional ``decode[server]`` extra installed.
"""

from __future__ import annotations

from .config import DEFAULT_HOST, DEFAULT_PORT, MCPServerConfig
from .server import DecodeMCPServer

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DecodeMCPServer",
    "MCPServerConfig",
]
