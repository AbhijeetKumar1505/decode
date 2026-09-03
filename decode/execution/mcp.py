"""MCP execution provider — every MCP server is just another provider.

MCP tools are structured calls (name + JSON arguments), not shell strings, so
this provider interprets a command as JSON: ``{"tool": "<name>", "arguments":
{...}}``. The transport is an injectable client (protocol below), so the
provider is fully testable with a fake. The real client is built by
:func:`decode.extensions.mcp_client.build_client` (optional ``mcp`` SDK, stdio
transport only) and bound via ``MCPServerManager.executor_for``.
"""

import json
from typing import Any, Protocol

from .base import Command, ExecutionProvider, ExecutionResult, command_display


class MCPClient(Protocol):
    """Minimal transport contract an MCP client must satisfy."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...

    async def check(self) -> bool: ...


class MCPExecutor(ExecutionProvider):
    def __init__(
        self,
        server: str = "",
        client: MCPClient | None = None,
        config: dict | None = None,
    ):
        self._server = server
        self._client = client
        self._config = config or {}

    @property
    def name(self) -> str:
        return f"mcp/{self._server}" if self._server else "mcp"

    @staticmethod
    def encode(tool: str, arguments: dict[str, Any] | None = None) -> str:
        """Helper: build the JSON command string this provider expects."""
        return json.dumps({"tool": tool, "arguments": arguments or {}})

    async def execute(
        self, command: Command, timeout: int = 60, env: dict[str, str] | None = None
    ) -> ExecutionResult:
        display = command_display(command)
        if not isinstance(command, str):
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr="MCP commands require a structured JSON payload",
                exit_code=-1,
                error="invalid_mcp_command",
            )
        if self._client is None:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr="No MCP client configured for this server",
                exit_code=-1,
                error="mcp_not_configured",
            )
        try:
            payload = json.loads(command)
            tool = payload["tool"]
            arguments = payload.get("arguments", {})
        except (json.JSONDecodeError, KeyError, TypeError):
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr='MCP command must be JSON: {"tool": "<name>", "arguments": {...}}',
                exit_code=-1,
                error="invalid_mcp_command",
            )
        try:
            result = await self._client.call_tool(tool, arguments)
        except Exception as e:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=str(e),
                exit_code=-1,
                error=str(e),
                metadata={"tool": tool},
            )
        stdout = result if isinstance(result, str) else json.dumps(result, default=str)
        return ExecutionResult(
            command=display,
            provider=self.name,
            success=True,
            stdout=stdout,
            exit_code=0,
            metadata={"tool": tool},
        )

    async def check_health(self) -> bool:
        if self._client is None:
            return False
        try:
            return await self._client.check()
        except Exception:
            return False
