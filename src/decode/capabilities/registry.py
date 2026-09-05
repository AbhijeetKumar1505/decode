"""Unified capability registry (subsystem 05, §8).

One source-tagged view over every capability the agent can select, regardless of
where it comes from: native built-ins, the system-tool gateway (shell/discovery/
sessions), markdown playbooks, and external MCP tools. The agent asks "what
capabilities are available for this task?" — it never reasons about *where* a
capability lives. Registration (here) is separate from execution (the governed
coordinator): registering a capability never runs anything.

System tools deliberately do NOT get per-binary entries — they stay behind the
single ``shell_command`` + ``list_tools`` capabilities (discovered, not
catalogued), preserving the universal-agent pivot.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..schema import TaskMode
from .coding import coding_tool_list

_SYSTEM_GATEWAY = {
    "shell_command",
    "list_tools",
    "host_session",
    "session_open",
    "session_exec",
    "session_close",
}

# Playbooks in these categories are general-purpose (engineering / agent core)
# rather than security-domain, so they are offered in every task mode, including
# CODING. Security-domain playbooks (e.g. ``web_scanning``) stay gated to
# SECURITY/HYBRID. ``agent_core`` is also the default category for a markdown
# playbook with no explicit category.
GENERAL_SKILL_CATEGORIES = frozenset({"agent_core"})


class Capability(BaseModel):
    name: str
    source: str  # native | system | skill | mcp | plugin
    type: str  # host | coding | system | playbook | mcp
    description: str = ""
    risk: str = "write"
    executor: str = "internal"
    available: bool = True
    server: str = ""  # mcp routing
    tool: str = ""  # mcp raw tool name
    category: str = ""  # skill category, used to gate playbooks by task mode

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "source": self.source,
        }


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        self._caps.setdefault(
            cap.name, cap
        )  # first registration wins (host precedence)

    def get(self, name: str) -> Capability | None:
        return self._caps.get(name)

    def all(self) -> list[Capability]:
        return list(self._caps.values())

    def by_source(self, source: str) -> list[Capability]:
        return [c for c in self._caps.values() if c.source == source]

    def resolve(self, mode: TaskMode) -> list[dict[str, Any]]:
        """The per-turn tool surface for ``mode`` (see the mode rules in the
        capability resolver): native/system always; coding for coding/hybrid;
        security-domain playbooks for security/hybrid; general-purpose
        (engineering) playbooks always; MCP always (opt-in by being configured)."""
        include_coding = mode in (TaskMode.CODING, TaskMode.HYBRID)
        include_skills = mode in (TaskMode.SECURITY, TaskMode.HYBRID)
        out: list[dict[str, Any]] = []
        for cap in self._caps.values():
            if not cap.available:
                continue
            if cap.type == "coding" and not include_coding:
                continue
            if cap.source == "skill" and not include_skills:
                # General-purpose (engineering) playbooks stay available even
                # outside security/hybrid; only security-domain playbooks are gated.
                if cap.category not in GENERAL_SKILL_CATEGORIES:
                    continue
            out.append(cap.descriptor())
        return out


def build_registry(
    host_tools: list[dict[str, Any]],
    skill_tools: list[dict[str, Any]],
    mcp_descriptors: list[Any] | None = None,
    *,
    include_coding: bool = True,
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for tool in host_tools:
        name = tool.get("name", "")
        is_gateway = name in _SYSTEM_GATEWAY
        registry.register(
            Capability(
                name=name,
                source="system" if is_gateway else "native",
                type="system" if is_gateway else "host",
                description=tool.get("description", ""),
                risk=str(tool.get("risk", "write")),
            )
        )
    if include_coding:
        for tool in coding_tool_list():
            registry.register(
                Capability(
                    name=tool["name"],
                    source="native",
                    type="coding",
                    description=tool["description"],
                    risk=tool["risk"],
                )
            )
    for tool in skill_tools:
        registry.register(
            Capability(
                name=tool.get("name", ""),
                source="skill",
                type="playbook",
                description=tool.get("description", ""),
                risk=str(tool.get("risk", "write")),
                category=str(tool.get("category", "")),
            )
        )
    for desc in mcp_descriptors or []:
        registry.register(
            Capability(
                name=desc.name,
                source="mcp",
                type="mcp",
                description=desc.description,
                risk=desc.risk,
                executor=f"mcp/{desc.server}",
                server=desc.server,
                tool=desc.tool,
            )
        )
    return registry
