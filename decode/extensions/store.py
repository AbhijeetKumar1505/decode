"""Scoped JSON state for the extension layer.

Each store is one JSON file name (e.g. ``mcp.json``) resolved per scope. Reads
merge across scopes (project over user over system); writes target a single
scope. Used by the MCP and plugin managers to persist registered servers and
installed plugins without touching the env-based :class:`decode.config.Config`.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .paths import PRECEDENCE, Scope, ensure_scope, scope_root


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``overlay`` onto ``base`` (overlay wins). Returns a new dict."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class ScopedStore:
    def __init__(self, filename: str) -> None:
        self.filename = filename

    def read_scope(self, scope: Scope) -> Dict[str, Any]:
        root = scope_root(scope)
        if root is None:
            return {}
        path = root / self.filename
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def read_merged(self) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for scope in PRECEDENCE:
            merged = deep_merge(merged, self.read_scope(scope))
        return merged

    def write_scope(self, scope: Scope, data: Dict[str, Any]) -> None:
        root = ensure_scope(scope)
        path = root / self.filename
        path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def update_scope(self, scope: Scope, key: str, value: Any) -> Dict[str, Any]:
        data = self.read_scope(scope)
        data[key] = value
        self.write_scope(scope, data)
        return data

    def delete_key(self, scope: Scope, key: str) -> bool:
        data = self.read_scope(scope)
        if key not in data:
            return False
        del data[key]
        self.write_scope(scope, data)
        return True
