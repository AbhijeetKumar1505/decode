"""Stateful host command session.

A safe, portable stand-in for an interactive shell: commands run sequentially
sharing a working directory and environment, and every step is recorded to a
transcript that can be persisted as evidence. It is not a raw PTY — commands are
still argument vectors checked by ``CommandPolicy`` — so it stays governed while
supporting the compose-and-observe loop interactive tools need.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .operations import run_command
from .policy import CommandPolicy, FilesystemScope


class HostSession:
    def __init__(
        self,
        policy: CommandPolicy,
        scope: FilesystemScope | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._policy = policy
        self._scope = scope
        self.cwd = (
            str(Path(cwd).expanduser().resolve(strict=False)) if cwd else os.getcwd()
        )
        self.env = dict(env) if env is not None else dict(os.environ)
        self.transcript: list[dict[str, Any]] = []

    def run(self, argv: list[str]) -> dict[str, Any]:
        # `cd` mutates session state without spawning a process.
        if argv and argv[0] == "cd":
            target = Path(self.cwd) / (argv[1] if len(argv) > 1 else ".")
            resolved = target.expanduser().resolve(strict=False)
            if self._scope is not None and not self._scope.allows(
                resolved, write=False
            ):
                result = {"ok": False, "error": f"cd outside scope: {resolved}"}
            elif not resolved.is_dir():
                result = {"ok": False, "error": f"not a directory: {resolved}"}
            else:
                self.cwd = str(resolved)
                result = {"ok": True, "error": "", "cwd": self.cwd}
        else:
            result = run_command(argv, self._policy, cwd=self.cwd, env=self.env)
        self.transcript.append(
            {"command": [str(a) for a in argv], "cwd": self.cwd, "result": result}
        )
        return result

    def summary(self) -> dict[str, Any]:
        return {
            "cwd": self.cwd,
            "commands_run": len(self.transcript),
            "transcript": self.transcript,
        }
