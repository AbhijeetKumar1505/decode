"""Configuration and on-disk state for the De-code MCP/HTTP server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..hostcontrol import PermissionMode

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def runtime_root() -> Path:
    """Resolve ``$DECODE_HOME`` (or ``~/.decode``) freshly, honouring test overrides."""
    configured = os.getenv("DECODE_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".decode"


def state_dir() -> Path:
    return runtime_root() / "mcp"


def state_file() -> Path:
    """Path of the JSON file recording the running server's endpoint/pid."""
    return state_dir() / "server.json"


@dataclass
class MCPServerConfig:
    """How the server binds and what it is allowed to do.

    ``mode`` maps to the governance ``PermissionMode``:
      * ``plan`` — every tool is denied (inspection only).
      * ``ask``  — READ tools run; WRITE/DESTRUCTIVE need approval, so on a
        headless server (no approval callback) they are denied. Safe default.
      * ``auto`` — WRITE tools run without prompting. Powerful; local-only.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    mode: PermissionMode = PermissionMode.ASK
    read_roots: list[str] = field(default_factory=lambda: [str(Path.cwd())])
    write_roots: list[str] = field(default_factory=list)
    # None → expose every host capability; a list restricts to those names.
    enabled_tools: list[str] | None = None

    @property
    def is_local(self) -> bool:
        return self.host in ("127.0.0.1", "localhost", "::1")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "mode": self.mode.value,
            "read_roots": list(self.read_roots),
            "write_roots": list(self.write_roots),
            "enabled_tools": (
                list(self.enabled_tools) if self.enabled_tools is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPServerConfig:
        mode = data.get("mode", PermissionMode.ASK.value)
        return cls(
            host=data.get("host", DEFAULT_HOST),
            port=int(data.get("port", DEFAULT_PORT)),
            mode=mode if isinstance(mode, PermissionMode) else PermissionMode(mode),
            read_roots=list(data.get("read_roots") or [str(Path.cwd())]),
            write_roots=list(data.get("write_roots") or []),
            enabled_tools=(
                list(data["enabled_tools"]) if data.get("enabled_tools") else None
            ),
        )
