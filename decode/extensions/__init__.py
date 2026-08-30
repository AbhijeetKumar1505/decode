"""Extension layer: scoped config, MCP servers, and plugin packages.

Three tool sources sit behind one registry — native/built-in capabilities,
system tools (discovered, shell-driven), and external providers (MCP servers and
plugin packages). This package owns configuration and installation of the
external providers; execution still flows through the governed coordinator.
"""

from .manager import ExtensionManager
from .mcp_manager import MCPManager, MCPServerSpec
from .paths import PRECEDENCE, Scope, scope_root
from .plugin_manager import PluginManager, PluginManifest
from .store import ScopedStore, deep_merge

__all__ = [
    "ExtensionManager",
    "MCPManager",
    "MCPServerSpec",
    "PluginManager",
    "PluginManifest",
    "PRECEDENCE",
    "Scope",
    "scope_root",
    "ScopedStore",
    "deep_merge",
]
