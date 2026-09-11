"""Native MCP-protocol binding over stdio (optional ``mcp`` SDK, v1).

Wraps :class:`DecodeMCPServer` so standard MCP clients (Claude Desktop, IDEs,
other agents) can discover and invoke the governed De-code capabilities
directly. Every call still routes through the ``ExecutionCoordinator``, so
governance, approval, audit, and evidence are unchanged.

The SDK is optional — install it with ``pip install 'decode[mcp]'``. Imports are
lazy so this module stays importable without the extra; ``mcp_tool_payloads`` is
pure and SDK-free.
"""

import json
from typing import Any

from .server import DecodeMCPServer

_MCP_MISSING = (
    "The native MCP stdio server needs the MCP SDK. "
    "Install it with: pip install 'decode[mcp]'"
)


def mcp_tool_payloads(server: DecodeMCPServer) -> list[dict[str, Any]]:
    """Tool descriptors shaped for the MCP SDK (name/description/inputSchema).

    Pure and SDK-free so it can be unit-tested without the ``mcp`` package.
    """
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["input_schema"],
        }
        for tool in server.list_tools()
    ]


def build_mcp_server(server: DecodeMCPServer):
    """Build a low-level MCP ``Server`` wired to the governed De-code tools."""
    try:
        from mcp import types
        from mcp.server.lowlevel import Server
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(_MCP_MISSING) from exc

    app = Server("decode")

    @app.list_tools()
    async def _list_tools() -> list:
        return [
            types.Tool(
                name=payload["name"],
                description=payload["description"],
                inputSchema=payload["inputSchema"],
            )
            for payload in mcp_tool_payloads(server)
        ]

    @app.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None):
        result = await server.call_tool(name, arguments or {})
        return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    return app


async def run_stdio(server: DecodeMCPServer) -> None:
    """Serve the governed tools over stdio until the client disconnects."""
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(_MCP_MISSING) from exc

    app = build_mcp_server(server)
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())
