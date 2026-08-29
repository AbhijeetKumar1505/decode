"""Governed host-control subsystem.

Extends the typed-capability model to general host operations — files, search,
processes, services, ad-hoc commands, and stateful sessions — each scoped, risk
classified, approvable, and auditable, so the agent can harness a host the way a
general assistant does without discarding scope, approval, evidence, or audit.
"""

from ..skills.base import RiskLevel
from .hooks import HookEvent, HookRegistry
from .policy import (
    CommandPolicy,
    FilesystemScope,
    PermissionMode,
    ScopeViolation,
    resolve_mode_decision,
)
from .session import HostSession

# Canonical host capabilities: name -> (baseline risk, description).
# Baseline risk gates the capability; shell_command's per-command risk is
# resolved by CommandPolicy.classify and surfaced in the result.
HOST_CAPABILITY_META = {
    "file_read": (RiskLevel.READ, "Read a file within the authorized filesystem scope"),
    "file_list": (RiskLevel.READ, "List a directory within the authorized scope"),
    "file_search": (RiskLevel.READ, "Search files for a pattern within scope"),
    "file_write": (RiskLevel.WRITE, "Write a file within the writable scope"),
    "file_edit": (RiskLevel.WRITE, "Replace text in a file within the writable scope"),
    "file_fetch": (RiskLevel.WRITE, "Copy or stage a file between scoped paths"),
    "list_tools": (RiskLevel.READ, "List command-line tools installed on this host (optionally filtered by name); use it to discover what you can run via shell_command"),
    "process_list": (RiskLevel.READ, "List running processes"),
    "process_kill": (RiskLevel.DESTRUCTIVE, "Terminate a process by PID"),
    "service_status": (RiskLevel.READ, "Query a system service state"),
    "service_control": (RiskLevel.DESTRUCTIVE, "Start, stop, or restart a system service"),
    "shell_command": (RiskLevel.WRITE, "Run any installed CLI tool by its command line (policy-checked, per-command risk-classified, scoped, audited); if the tool is absent the result reports it"),
    "host_session": (RiskLevel.WRITE, "Run a sequence of commands in a stateful session"),
    "session_open": (RiskLevel.READ, "Open a persistent shell session that keeps its working directory and environment across turns"),
    "session_exec": (RiskLevel.WRITE, "Run one command in the persistent session (cwd/env persist; per-command risk-classified). Opens the session on first use"),
    "session_close": (RiskLevel.READ, "Close the persistent session and return its transcript summary"),
}

HOST_CAPABILITIES = tuple(HOST_CAPABILITY_META)

__all__ = [
    "CommandPolicy",
    "FilesystemScope",
    "PermissionMode",
    "ScopeViolation",
    "resolve_mode_decision",
    "HookEvent",
    "HookRegistry",
    "HostSession",
    "HOST_CAPABILITY_META",
    "HOST_CAPABILITIES",
]
