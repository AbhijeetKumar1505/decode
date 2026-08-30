"""ExtensionManager — the single entry point for installation/configuration.

Owns the scoped config and, as later phases land, the MCP and plugin managers.
Keeping installation/configuration here (never in the agent loop) preserves the
install -> register -> execute separation: the manager configures and registers
capabilities; the agent only ever selects and executes already-registered ones
through the governed coordinator.
"""

from __future__ import annotations

from typing import Any, Dict

from .paths import Scope
from .store import ScopedStore


class ExtensionManager:
    def __init__(self, default_scope: Scope = Scope.USER) -> None:
        self.default_scope = default_scope
        self.config = ScopedStore("config.json")
        self._mcp: Any = None
        self._plugins: Any = None

    @property
    def mcp(self) -> Any:
        """The MCP server manager (lazily constructed)."""
        if self._mcp is None:
            from .mcp_manager import MCPManager

            self._mcp = MCPManager(default_scope=self.default_scope)
        return self._mcp

    @property
    def plugins(self) -> Any:
        """The plugin manager (lazily constructed), sharing this MCP manager."""
        if self._plugins is None:
            from .plugin_manager import PluginManager

            self._plugins = PluginManager(default_scope=self.default_scope, mcp_manager=self.mcp)
        return self._plugins

    def playbook_dirs(self) -> list:
        """Skill directories contributed by enabled plugins (for DECODE_PLAYBOOKS_DIR)."""
        return self.plugins.enabled_skill_dirs()

    def settings(self) -> Dict[str, Any]:
        """Merged settings across all scopes (project over user over system)."""
        return self.config.read_merged()
