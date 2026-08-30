"""MCP server manager — registration, discovery, and lazy lifecycle.

An MCP server is an external tool provider. This manager persists server
configuration (scoped), starts a server lazily on first use, lists its tools
(``tools/list``), and exposes them as descriptors the capability registry can
register. Execution of an MCP tool still flows through the governed coordinator
via :class:`decode.execution.mcp.MCPExecutor`; risk is not inferred from an argv
(MCP calls are opaque structured payloads) but declared per server.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from ..execution.mcp import MCPExecutor
from .paths import Scope
from .store import ScopedStore

_VALID_RISK = {"read", "write", "destructive"}


class MCPServerSpec(BaseModel):
    name: str
    transport: str = "stdio"  # stdio | http
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: str = ""
    enabled: bool = True
    #: Declared risk for governance (MCP payloads cannot be argv-classified).
    risk: str = "write"
    description: str = ""


class MCPToolDescriptor(BaseModel):
    server: str
    name: str  # namespaced, e.g. "mongodb.find"
    tool: str  # raw tool name on the server
    description: str = ""
    risk: str = "write"
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class MCPToolProvider(Protocol):
    """What a discovery client must satisfy (a superset of MCPExecutor's client)."""

    async def list_tools(self) -> List[Dict[str, Any]]: ...
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any: ...


ClientFactory = Callable[[MCPServerSpec], MCPToolProvider]


def _default_client_factory(spec: MCPServerSpec) -> MCPToolProvider:  # pragma: no cover
    from .mcp_client import build_client

    return build_client(spec)


class MCPManager:
    def __init__(
        self,
        default_scope: Scope = Scope.USER,
        store: Optional[ScopedStore] = None,
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        self._store = store or ScopedStore("mcp.json")
        self._default_scope = default_scope
        self._client_factory = client_factory or _default_client_factory
        self._clients: Dict[str, MCPToolProvider] = {}
        self._tools_cache: Dict[str, List[MCPToolDescriptor]] = {}

    # ── configuration (install/register) ────────────────────────────────
    def add(self, spec: MCPServerSpec, scope: Optional[Scope] = None) -> None:
        if spec.risk not in _VALID_RISK:
            raise ValueError(f"risk must be one of {sorted(_VALID_RISK)}")
        self._store.update_scope(scope or self._default_scope, spec.name, spec.model_dump())

    def remove(self, name: str, scope: Optional[Scope] = None) -> bool:
        self._tools_cache.pop(name, None)
        self._clients.pop(name, None)
        return self._store.delete_key(scope or self._default_scope, name)

    def list_servers(self) -> Dict[str, MCPServerSpec]:
        return {
            name: MCPServerSpec(**{**data, "name": name})
            for name, data in self._store.read_merged().items()
            if isinstance(data, dict)
        }

    def get(self, name: str) -> Optional[MCPServerSpec]:
        return self.list_servers().get(name)

    def set_enabled(self, name: str, enabled: bool, scope: Optional[Scope] = None) -> bool:
        target = scope or self._default_scope
        data = self._store.read_scope(target)
        if name not in data:
            # materialize from the merged view so enable/disable works at this scope
            merged = self.get(name)
            if merged is None:
                return False
            data[name] = merged.model_dump()
        data[name]["enabled"] = enabled
        self._store.write_scope(target, data)
        self._tools_cache.pop(name, None)
        return True

    # ── discovery / lifecycle (lazy) ────────────────────────────────────
    async def _client(self, name: str) -> MCPToolProvider:
        if name not in self._clients:
            spec = self.get(name)
            if spec is None:
                raise KeyError(f"unknown MCP server: {name}")
            client = self._client_factory(spec)
            initialize = getattr(client, "initialize", None)
            if initialize is not None:
                result = initialize()
                if hasattr(result, "__await__"):
                    await result
            self._clients[name] = client
        return self._clients[name]

    async def discover(self, name: str, *, refresh: bool = False) -> List[MCPToolDescriptor]:
        spec = self.get(name)
        if spec is None or not spec.enabled:
            return []
        if not refresh and name in self._tools_cache:
            return self._tools_cache[name]
        client = await self._client(name)
        raw = await client.list_tools()
        descriptors = [
            MCPToolDescriptor(
                server=name,
                name=f"{name}.{tool.get('name', '')}",
                tool=str(tool.get("name", "")),
                description=str(tool.get("description", "")),
                risk=spec.risk,
                input_schema=tool.get("inputSchema") or tool.get("input_schema") or {},
            )
            for tool in raw
            if tool.get("name")
        ]
        self._tools_cache[name] = descriptors
        return descriptors

    async def available_tools(self) -> List[MCPToolDescriptor]:
        tools: List[MCPToolDescriptor] = []
        for name, spec in self.list_servers().items():
            if spec.enabled:
                tools.extend(await self.discover(name))
        return tools

    def executor_for(self, name: str) -> MCPExecutor:
        """An MCPExecutor bound to the (already-started) client for governed calls."""
        return MCPExecutor(server=name, client=self._clients.get(name))
