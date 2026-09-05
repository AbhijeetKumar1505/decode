"""Host-control agent — first-class general OS operations.

Owns the host capability family (files, search, processes, services, ad-hoc
commands, stateful sessions) and executes them through the governed
``hostcontrol`` operations. Path and command policy come from the execution
context and default to fail-closed (an empty ``FilesystemScope`` denies every
path; a missing ``CommandPolicy`` denies every command), so host control is
never available without an explicit, scoped grant.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from ..hostcontrol import CommandPolicy, FilesystemScope, HostSession
from ..hostcontrol import operations as ops
from ..hostcontrol.policy import RiskLevel as _HostRisk
from .base import Agent, AgentResult


class HostAgent(Agent):
    domain = "host"

    @property
    def capabilities(self) -> list[str]:
        return [
            "file_read",
            "file_list",
            "file_search",
            "file_write",
            "file_edit",
            "file_fetch",
            "list_tools",
            "process_list",
            "process_kill",
            "service_status",
            "service_control",
            "shell_command",
            "host_session",
        ]

    async def execute_internal(self, node: Any, context: dict) -> AgentResult:
        params = node.params or {}
        scope: FilesystemScope = context.get("filesystem_scope") or FilesystemScope()
        policy: CommandPolicy | None = context.get("command_policy")
        # stdin (e.g. a sudo password) travels in the execution context, never in
        # node.params, so it is never audited, logged, or stored as evidence.
        stdin: str | None = context.get("stdin")
        try:
            result = self._dispatch(node.capability, params, scope, policy, stdin)
        except Exception as exc:  # never leak a stack trace as an execution result
            return self._result(
                node.capability, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            )
        return self._result(node.capability, result)

    def _dispatch(
        self,
        capability: str,
        params: dict,
        scope: FilesystemScope,
        policy: CommandPolicy | None,
        stdin: str | None = None,
    ) -> dict:
        if capability == "file_read":
            return ops.file_read(params["path"], scope)
        if capability == "file_list":
            return ops.file_list(params["path"], scope)
        if capability == "file_search":
            return ops.file_search(
                params["root"], params["pattern"], scope, glob=params.get("glob", "*")
            )
        if capability == "file_write":
            return ops.file_write(params["path"], params.get("content", ""), scope)
        if capability == "file_edit":
            return ops.file_edit(params["path"], params["old"], params["new"], scope)
        if capability == "file_fetch":
            return ops.file_fetch(params["source"], params["dest"], scope)
        if capability == "list_tools":
            return ops.list_tools(
                params.get("query", ""), int(params.get("limit", 400))
            )
        if capability == "process_list":
            return ops.process_list()
        if capability == "process_kill":
            return ops.process_kill(params["pid"])
        if capability == "service_status":
            return ops.service_status(params["name"])
        if capability == "service_control":
            return ops.service_control(params["name"], params["action"])
        if capability == "shell_command":
            return self._shell(params, policy, stdin)
        if capability == "host_session":
            return self._session(params.get("commands", ""), scope, policy)
        return {"ok": False, "error": f"unknown host capability: {capability}"}

    @staticmethod
    def _resolve_argv(params: dict) -> list[str]:
        """Accept either a pre-split ``argv`` list or a ``command`` string.

        ``argv`` avoids shell-quoting ambiguity and is preferred; ``command`` is
        kept for ergonomics and back-compat and is split with ``shlex`` (no shell
        is ever invoked — ``run_command`` execs the vector directly).
        """
        argv = params.get("argv")
        if isinstance(argv, (list, tuple)) and argv:
            return [str(a) for a in argv]
        return shlex.split(params.get("command", "") or "")

    def _shell(
        self, params: dict, policy: CommandPolicy | None, stdin: str | None = None
    ) -> dict:
        if policy is None:
            return {
                "ok": False,
                "error": "no command policy in scope; shell command denied",
            }
        argv = self._resolve_argv(params)
        if not argv:
            return {"ok": False, "error": "empty command"}
        # A DESTRUCTIVE command may not run under this WRITE-gated capability;
        # the coordinator resolves per-command risk before the gate (Phase 1 wiring).
        if policy.classify(argv) is _HostRisk.DESTRUCTIVE:
            return {
                "ok": False,
                "error": "command classified DESTRUCTIVE; not permitted via shell_command",
            }
        # For a sudo command with a supplied password, read it from stdin (-S) so
        # sudo never blocks on a tty prompt. The password itself stays in stdin.
        from pathlib import Path as _Path

        is_sudo = _Path(str(argv[0])).name == "sudo"
        if stdin is not None and is_sudo and "-S" not in argv[1:]:
            argv = [argv[0], "-S", "-p", ""] + argv[1:]
        return ops.run_command(argv, policy, stdin=stdin)

    def _session(
        self, commands: str, scope: FilesystemScope, policy: CommandPolicy | None
    ) -> dict:
        if policy is None:
            return {"ok": False, "error": "no command policy in scope; session denied"}
        try:
            steps = json.loads(commands)
        except (json.JSONDecodeError, TypeError):
            return {
                "ok": False,
                "error": "commands must be a JSON list of argument vectors",
            }
        if not isinstance(steps, list):
            return {
                "ok": False,
                "error": "commands must be a JSON list of argument vectors",
            }
        session = HostSession(policy, scope=scope)
        for step in steps:
            argv = step if isinstance(step, list) else shlex.split(str(step))
            if argv and policy.classify(argv) is _HostRisk.DESTRUCTIVE:
                session.transcript.append(
                    {
                        "command": argv,
                        "cwd": session.cwd,
                        "result": {"ok": False, "error": "DESTRUCTIVE step skipped"},
                    }
                )
                continue
            session.run(argv)
        summary = session.summary()
        summary["ok"] = True
        summary["error"] = ""
        return summary

    def _result(self, capability: str, data: dict) -> AgentResult:
        ok = bool(data.get("ok"))
        error = "" if ok else str(data.get("error", "host operation failed"))
        summary = "ok" if ok else error
        return AgentResult(
            agent=self.domain,
            capability=capability,
            success=ok,
            summary=summary[:300],
            output=""
            if not ok
            else json.dumps(
                {k: v for k, v in data.items() if k not in ("ok", "error")}
            )[:2000],
            error=error,
            normalized={k: v for k, v in data.items() if k not in ("ok", "error")},
        )
