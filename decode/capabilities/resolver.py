"""Per-turn capability resolver (subsystem 05).

Rather than exposing every tool on every turn, the resolver narrows the surface
to what the current task mode needs: coding tasks do not need the security
playbooks, and security tasks do not need the coding capabilities. Host
capabilities (files, search, shell, discovery) are universal and always present.
"""

from __future__ import annotations

from typing import Any

from ..schema import TaskMode
from .coding import coding_tool_list


def resolve_tools(
    mode: TaskMode,
    host_tools: list[dict[str, Any]],
    skill_tools: list[dict[str, Any]],
    *,
    include_coding: bool | None = None,
    include_skills: bool | None = None,
) -> list[dict[str, Any]]:
    """Return the tool subset to expose for ``mode``.

    - CODING: host + coding capabilities (no security playbooks).
    - SECURITY: host + skill playbooks (no coding capabilities).
    - HYBRID: everything.

    ``include_coding`` / ``include_skills`` override the mode defaults when set.
    """
    if include_coding is None:
        include_coding = mode in (TaskMode.CODING, TaskMode.HYBRID)
    if include_skills is None:
        include_skills = mode in (TaskMode.SECURITY, TaskMode.HYBRID)

    tools: list[dict[str, Any]] = list(host_tools)
    if include_coding:
        tools += coding_tool_list()
    if include_skills:
        tools += list(skill_tools)

    # De-duplicate by name, preserving first occurrence (host wins).
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name", "")
        if name and name not in seen:
            seen.add(name)
            unique.append(tool)
    return unique
