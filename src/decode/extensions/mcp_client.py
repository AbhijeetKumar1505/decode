"""Real MCP transport adapters (optional ``mcp`` SDK).

Supports ``stdio`` (subprocess), ``http`` / ``streamable-http`` (the modern MCP
HTTP transport), and ``sse`` (the legacy Server-Sent-Events transport). Install
the SDK with the ``mcp`` extra (``pip install .[mcp]`` / ``poetry install -E
mcp``).

Kept behind an optional import and excluded from coverage: exercising it needs a
live MCP server. The manager and executor are fully tested with injected fake
clients; this module only wires the actual SDK. Each call opens a short-lived
session (connect -> initialize -> op -> close), which trades throughput for
lifecycle simplicity and correctness — a persistent-session pool can replace it
once validated against live servers.
"""

from __future__ import annotations

from typing import Any

from .mcp_manager import MCPServerSpec, MCPToolProvider


class _StdioMCPClient:  # pragma: no cover - requires a live MCP server
    def __init__(self, spec: MCPServerSpec) -> None:
        self._spec = spec

    def _params(self):
        from mcp import StdioServerParameters

        return StdioServerParameters(
            command=self._spec.command,
            args=list(self._spec.args),
            env=dict(self._spec.env) or None,
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(self._params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "inputSchema": getattr(t, "inputSchema", {}),
                    }
                    for t in listing.tools
                ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(self._params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return getattr(result, "content", result)

    async def check(self) -> bool:
        try:
            await self.list_tools()
            return True
        except Exception:
            return False


class _HTTPMCPClient:  # pragma: no cover - requires a live MCP server
    """Client for the modern MCP streamable-HTTP transport, and legacy SSE."""

    def __init__(self, spec: MCPServerSpec, *, sse: bool = False) -> None:
        self._spec = spec
        self._sse = sse

    def _connect(self):
        if self._sse:
            from mcp.client.sse import sse_client

            return sse_client(self._spec.url, headers=dict(self._spec.env) or None)
        from mcp.client.streamable_http import streamablehttp_client

        return streamablehttp_client(
            self._spec.url, headers=dict(self._spec.env) or None
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        from mcp import ClientSession

        async with self._connect() as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "inputSchema": getattr(t, "inputSchema", {}),
                    }
                    for t in listing.tools
                ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        from mcp import ClientSession

        async with self._connect() as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return getattr(result, "content", result)

    async def check(self) -> bool:
        try:
            await self.list_tools()
            return True
        except Exception:
            return False


_HTTP_TRANSPORTS = {"http", "streamable-http", "streamable_http", "streamablehttp"}


def build_client(spec: MCPServerSpec) -> MCPToolProvider:  # pragma: no cover
    try:
        import mcp  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "The 'mcp' package is required to run MCP servers; install it or "
            "provide a client factory."
        ) from exc
    if spec.transport == "stdio":
        return _StdioMCPClient(spec)
    if spec.transport in _HTTP_TRANSPORTS:
        if not spec.url:
            raise ValueError(
                f"MCP server '{spec.name}' needs a --url for http transport"
            )
        return _HTTPMCPClient(spec)
    if spec.transport == "sse":
        if not spec.url:
            raise ValueError(
                f"MCP server '{spec.name}' needs a --url for sse transport"
            )
        return _HTTPMCPClient(spec, sse=True)
    raise NotImplementedError(f"MCP transport '{spec.transport}' is not yet wired")
