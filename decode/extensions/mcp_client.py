"""Real MCP transport adapters (optional ``mcp`` SDK).

Kept behind an optional import and excluded from coverage: exercising it needs a
live MCP server. The manager and executor are fully tested with injected fake
clients; this module only wires the actual SDK. Each call opens a short-lived
session (connect -> initialize -> op -> close), which trades throughput for
lifecycle simplicity and correctness — a persistent-session pool can replace it
once validated against live servers.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .mcp_manager import MCPServerSpec, MCPToolProvider


class _StdioMCPClient:  # pragma: no cover - requires a live MCP server
    def __init__(self, spec: MCPServerSpec) -> None:
        self._spec = spec

    def _params(self):
        from mcp import StdioServerParameters

        return StdioServerParameters(
            command=self._spec.command, args=list(self._spec.args), env=dict(self._spec.env) or None
        )

    async def list_tools(self) -> List[Dict[str, Any]]:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(self._params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                return [
                    {"name": t.name, "description": t.description or "", "inputSchema": getattr(t, "inputSchema", {})}
                    for t in listing.tools
                ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
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
    raise NotImplementedError(f"MCP transport '{spec.transport}' is not yet wired")
