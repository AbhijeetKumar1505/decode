"""Typed coding capabilities (hybrid model, subsystem 05).

These are the few capabilities where a typed interface + result parsing pays off:
git, tests, build, and patch application. They add **no new execution path** —
each one translates to a governed ``shell_command`` argument vector that runs
through the same ``HostController``/coordinator/policy as everything else, so
per-command risk classification and audit still apply.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

# name -> (description, baseline risk label for the tool listing)
CODING_CAPABILITIES: dict[str, dict[str, str]] = {
    "git_status": {
        "description": "Show the working-tree status (git status --short)",
        "risk": "read",
    },
    "git_diff": {
        "description": "Show the working-tree diff, optionally for a path",
        "risk": "read",
    },
    "git_log": {
        "description": "Show recent commit history (git log --oneline)",
        "risk": "read",
    },
    "git_commit": {
        "description": "Commit staged changes with a message",
        "risk": "write",
    },
    "test_run": {
        "description": "Run the test suite (default: pytest -q)",
        "risk": "write",
    },
    "build_run": {
        "description": "Run the project build (default: make)",
        "risk": "write",
    },
    "patch_apply": {
        "description": "Apply a unified diff to the working tree (git apply)",
        "risk": "write",
    },
}


def is_coding_capability(name: str) -> bool:
    return name in CODING_CAPABILITIES


def coding_tool_list() -> list[dict[str, str]]:
    return [
        {"name": name, "description": meta["description"], "risk": meta["risk"]}
        for name, meta in CODING_CAPABILITIES.items()
    ]


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError("argument must be a single line")
    return text


def build_coding_command(
    name: str, params: dict[str, Any]
) -> tuple[list[str], str | None]:
    """Translate a coding capability to ``(argv, stdin)``.

    Raises ``ValueError`` on an unknown capability or invalid arguments.
    """
    params = params or {}
    if name == "git_status":
        return ["git", "status", "--short"], None
    if name == "git_diff":
        argv = ["git", "diff"]
        path = _clean(params.get("path", ""))
        if params.get("staged"):
            argv.append("--staged")
        if path:
            argv += ["--", path]
        return argv, None
    if name == "git_log":
        limit = int(params.get("limit", 10) or 10)
        limit = max(1, min(limit, 100))
        return ["git", "log", "--oneline", f"-n{limit}"], None
    if name == "git_commit":
        message = _clean(params.get("message", ""))
        if not message:
            raise ValueError("git_commit requires a 'message'")
        argv = ["git", "commit", "-m", message]
        if params.get("all"):
            argv.insert(2, "-a")
        return argv, None
    if name == "test_run":
        command = str(params.get("command", "") or "pytest -q").strip()
        argv = shlex.split(command)
        if not argv:
            raise ValueError("test_run command is empty")
        return argv, None
    if name == "build_run":
        command = str(params.get("command", "") or "make").strip()
        argv = shlex.split(command)
        if not argv:
            raise ValueError("build_run command is empty")
        return argv, None
    if name == "patch_apply":
        diff = params.get("diff", "")
        if not isinstance(diff, str) or not diff.strip():
            raise ValueError("patch_apply requires a unified 'diff' string")
        return ["git", "apply", "-"], diff
    raise ValueError(f"unknown coding capability: {name}")


_PYTEST_PASS = re.compile(r"(\d+)\s+passed")
_PYTEST_FAIL = re.compile(r"(\d+)\s+failed")
_PYTEST_ERROR = re.compile(r"(\d+)\s+error")


def summarize_coding_result(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Extract structured signals from a coding capability's shell result.

    Returns extra fields to merge into the observation ``data`` (richer
    observations, subsystem 08). Never raises.
    """
    extra: dict[str, Any] = {}
    stdout = str(data.get("stdout", ""))
    stderr = str(data.get("stderr", ""))
    exit_code = data.get("exit_code")
    if name == "test_run":
        blob = stdout + "\n" + stderr
        passed = _PYTEST_PASS.search(blob)
        failed = _PYTEST_FAIL.search(blob)
        errored = _PYTEST_ERROR.search(blob)
        extra["tests_passed"] = int(passed.group(1)) if passed else None
        extra["tests_failed"] = int(failed.group(1)) if failed else None
        extra["tests_errored"] = int(errored.group(1)) if errored else None
        extra["tests_ok"] = exit_code == 0
    elif name in ("git_diff",):
        extra["files_changed"] = stdout.count("diff --git ")
    elif name == "git_status":
        extra["changed_entries"] = len([ln for ln in stdout.splitlines() if ln.strip()])
    elif name in ("git_commit", "build_run", "patch_apply"):
        extra["ok"] = exit_code == 0
    return extra
