"""Transport-independent MCP server core.

Lists the governed De-code host capabilities as MCP-style tools and dispatches
calls through the ``ExecutionCoordinator`` — governance gate, bounded approval,
audit, and evidence all apply exactly as they do in the REPL. This object holds
no web state; the FastAPI/stdio transports in ``transport`` wrap it.
"""

from __future__ import annotations

from typing import Any

from ..governance import GovernanceGate, ScopePolicy
from ..hostcontrol import CommandPolicy, FilesystemScope
from ..hostcontrol.mcp import host_capability_tools
from ..runtime import (
    CoordinatedResult,
    ExecutionCoordinator,
    HostController,
)
from ..runtime.coordinator import ApprovalCallback
from .config import MCPServerConfig


class DecodeMCPServer:
    """Expose governed host capabilities to MCP/HTTP clients."""

    def __init__(
        self,
        config: MCPServerConfig | None = None,
        *,
        coordinator: ExecutionCoordinator | None = None,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.config = config or MCPServerConfig()
        self._scope = FilesystemScope(
            read_roots=[*self.config.read_roots, *self.config.write_roots],
            write_roots=list(self.config.write_roots),
        )
        self._policy = CommandPolicy()
        self._gate = GovernanceGate(ScopePolicy(allow_all=True), mode=self.config.mode)
        self._coordinator = coordinator or ExecutionCoordinator(
            self._gate, approval_callback=approval_callback
        )
        self._controller = HostController(self._coordinator, self._scope, self._policy)

    # -- discovery ---------------------------------------------------------
    def list_tools(self) -> list[dict[str, Any]]:
        """Governed host capabilities as MCP-style tool descriptors."""
        tools = host_capability_tools()
        if self.config.enabled_tools is not None:
            allowed = set(self.config.enabled_tools)
            tools = [t for t in tools if t["name"] in allowed]
        return tools

    def _tool_names(self) -> set[str]:
        return {t["name"] for t in self.list_tools()}

    # -- invocation --------------------------------------------------------
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run one governed tool; returns a normalized, JSON-safe result dict."""
        arguments = arguments or {}
        if name not in self._tool_names():
            return {
                "tool": name,
                "ok": False,
                "status": "error",
                "value": None,
                "error": f"unknown or disabled tool: {name}",
                "error_category": None,
                "duration": 0.0,
                "request_id": "",
            }
        result = await self._controller.run(name, arguments)
        return self._normalize(name, result)

    @staticmethod
    def _normalize(name: str, result: CoordinatedResult) -> dict[str, Any]:
        return {
            "tool": name,
            "ok": bool(result.success),
            "status": result.status.value,
            "value": result.value,
            "error": result.error,
            "error_category": (
                result.error_category.value if result.error_category else None
            ),
            "duration": result.duration,
            "request_id": result.request_id,
        }

    # -- health ------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "decode-mcp",
            "mode": self.config.mode.value,
            "tools": len(self.list_tools()),
        }
