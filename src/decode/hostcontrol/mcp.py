"""Expose host capabilities as MCP-style tool descriptors.

Lets the agentic loop (or an external MCP client) see the governed host
capabilities as callable tools. The descriptors are metadata only — actually
invoking a tool still routes through the ExecutionCoordinator and its gate.
"""

from __future__ import annotations

from typing import Any

from . import HOST_CAPABILITY_META

_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "file_read": {"path": "string"},
    "file_list": {"path": "string"},
    "file_search": {"root": "string", "pattern": "string", "glob": "string?"},
    "file_write": {"path": "string", "content": "string"},
    "file_edit": {"path": "string", "old": "string", "new": "string"},
    "file_fetch": {"source": "string", "dest": "string"},
    "list_tools": {
        "query": "string? (case-insensitive name filter)",
        "limit": "integer? (max results, default 400)",
    },
    "process_list": {},
    "process_kill": {"pid": "integer"},
    "service_status": {"name": "string"},
    "service_control": {"name": "string", "action": "enum[start,stop,restart]"},
    "shell_command": {
        "command": "string? (full command line, e.g. 'nmap -sV 10.0.0.5')",
        "argv": "string[]? (pre-split alternative to command)",
        "target": "string? (authorized network target for network I/O)",
    },
    "host_session": {"commands": "string (JSON list of argument vectors)"},
    "session_open": {"cwd": "string? (starting working directory)"},
    "session_exec": {
        "command": "string? (one command line)",
        "argv": "string[]? (pre-split alternative)",
    },
    "session_close": {},
}


def host_capability_tools() -> list[dict[str, Any]]:
    """Return MCP-style tool descriptors for every host capability."""
    from ..mcp.schema import normalize_input_schema

    tools: list[dict[str, Any]] = []
    for name, (risk, description) in HOST_CAPABILITY_META.items():
        raw_schema: dict[str, Any] = {
            "type": "object",
            "properties": _INPUT_SCHEMAS.get(name, {}),
        }
        if name in {"shell_command", "session_exec"}:
            raw_schema["oneOf"] = [
                {"required": ["command"]},
                {"required": ["argv"]},
            ]
        tools.append(
            {
                "name": name,
                "description": description,
                "risk": risk.value,
                "input_schema": normalize_input_schema(raw_schema),
                "governed": True,
            }
        )
    return tools
