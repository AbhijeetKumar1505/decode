"""Governed host operations: files, search, processes, services, commands.

Every function enforces its policy (``FilesystemScope`` / ``CommandPolicy``) and
fails closed, returning a structured result rather than raising for policy
denials so the coordinator can record them as denials. Raw bytes are hashed for
evidence and never silently exceeded; secret-looking content is left to the
coordinator's redaction on the way to telemetry.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import subprocess  # nosec B404 - governed, argument-vector only, policy-checked
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .policy import CommandPolicy, FilesystemScope, ScopeViolation

MAX_READ_BYTES = 1_000_000
MAX_SEARCH_MATCHES = 500
_COMMAND_TIMEOUT = 60


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ok(**fields: Any) -> Dict[str, Any]:
    return {"ok": True, "error": "", **fields}


def _deny(error: str) -> Dict[str, Any]:
    return {"ok": False, "error": error}


# ── files ────────────────────────────────────────────────────────────────

def file_read(path: str, scope: FilesystemScope, *, max_bytes: int = MAX_READ_BYTES) -> Dict[str, Any]:
    try:
        scope.check(path, write=False)
    except ScopeViolation as exc:
        return _deny(str(exc))
    target = Path(path)
    if not target.is_file():
        return _deny(f"not a readable file: {path}")
    raw = target.read_bytes()
    truncated = len(raw) > max_bytes
    body = raw[:max_bytes]
    return _ok(
        path=str(target),
        size_bytes=len(raw),
        sha256=_sha256(raw),
        truncated=truncated,
        content=body.decode("utf-8", errors="replace"),
    )


def file_list(path: str, scope: FilesystemScope) -> Dict[str, Any]:
    try:
        scope.check(path, write=False)
    except ScopeViolation as exc:
        return _deny(str(exc))
    target = Path(path)
    if not target.is_dir():
        return _deny(f"not a directory: {path}")
    entries: List[Dict[str, Any]] = []
    for child in sorted(target.iterdir()):
        try:
            stat = child.stat()
            entries.append({
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size_bytes": stat.st_size,
            })
        except OSError:
            continue
    return _ok(path=str(target), entries=entries, total=len(entries))


def file_search(
    root: str, pattern: str, scope: FilesystemScope, *,
    glob: str = "*", max_matches: int = MAX_SEARCH_MATCHES,
) -> Dict[str, Any]:
    try:
        scope.check(root, write=False)
    except ScopeViolation as exc:
        return _deny(str(exc))
    base = Path(root)
    if not base.exists():
        return _deny(f"path does not exist: {root}")
    files = [base] if base.is_file() else base.rglob("*")
    matches: List[Dict[str, Any]] = []
    needle = pattern.lower()
    for file in files:
        if len(matches) >= max_matches:
            break
        if not file.is_file() or not fnmatch.fnmatch(file.name, glob):
            continue
        if not scope.allows(file, write=False):
            continue
        try:
            for lineno, line in enumerate(file.read_text(errors="replace").splitlines(), 1):
                if needle in line.lower():
                    matches.append({"file": str(file), "line": lineno, "text": line.strip()[:200]})
                    if len(matches) >= max_matches:
                        break
        except OSError:
            continue
    return _ok(pattern=pattern, matches=matches, total=len(matches), truncated=len(matches) >= max_matches)


def file_write(path: str, content: str, scope: FilesystemScope) -> Dict[str, Any]:
    try:
        scope.check(path, write=True)
    except ScopeViolation as exc:
        return _deny(str(exc))
    target = Path(path)
    data = content.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return _ok(path=str(target), size_bytes=len(data), sha256=_sha256(data))


def file_edit(path: str, old: str, new: str, scope: FilesystemScope) -> Dict[str, Any]:
    try:
        scope.check(path, write=True)
    except ScopeViolation as exc:
        return _deny(str(exc))
    target = Path(path)
    if not target.is_file():
        return _deny(f"not a writable file: {path}")
    text = target.read_text(errors="replace")
    count = text.count(old)
    if count == 0:
        return _deny("old string not found; no changes made")
    updated = text.replace(old, new)
    data = updated.encode("utf-8")
    target.write_bytes(data)
    return _ok(path=str(target), replacements=count, sha256=_sha256(data))


def file_fetch(source: str, dest: str, scope: FilesystemScope) -> Dict[str, Any]:
    """Governed local copy (loot staging). Both ends must be in scope."""
    try:
        scope.check(source, write=False)
        scope.check(dest, write=True)
    except ScopeViolation as exc:
        return _deny(str(exc))
    src = Path(source)
    if not src.is_file():
        return _deny(f"source is not a file: {source}")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    data = Path(dest).read_bytes()
    return _ok(source=str(src), dest=str(dest), size_bytes=len(data), sha256=_sha256(data))


# ── processes and services ─────────────────────────────────────────────────

def process_list(*, limit: int = 200) -> Dict[str, Any]:
    try:
        import psutil
    except ImportError:
        return _deny("psutil is not available")
    procs: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "username"]):
        try:
            info = proc.info
            procs.append({"pid": info["pid"], "name": info.get("name", ""), "user": info.get("username", "")})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if len(procs) >= limit:
            break
    return _ok(processes=procs, total=len(procs))


def process_kill(pid: int) -> Dict[str, Any]:
    try:
        import psutil
    except ImportError:
        return _deny("psutil is not available")
    try:
        proc = psutil.Process(int(pid))
        name = proc.name()
        proc.terminate()
        return _ok(pid=int(pid), name=name, action="terminate")
    except psutil.NoSuchProcess:
        return _deny(f"no such process: {pid}")
    except psutil.AccessDenied:
        return _deny(f"access denied terminating pid {pid}")


def service_status(name: str) -> Dict[str, Any]:
    if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return _deny("invalid service name")
    result = run_command(["systemctl", "is-active", name], CommandPolicy(allowed_binaries={"systemctl"}))
    if not result["ok"]:
        return result
    return _ok(service=name, state=result["stdout"].strip() or "unknown")


def service_control(name: str, action: str) -> Dict[str, Any]:
    if action not in {"start", "stop", "restart"}:
        return _deny("action must be start, stop, or restart")
    if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return _deny("invalid service name")
    result = run_command(["systemctl", action, name], CommandPolicy(allowed_binaries={"systemctl"}))
    if not result["ok"]:
        return result
    return _ok(service=name, action=action, exit_code=result["exit_code"])


# ── governed ad-hoc command ────────────────────────────────────────────────

def run_command(
    argv: Sequence[str], policy: CommandPolicy, *, timeout: int = _COMMAND_TIMEOUT,
    cwd: str | None = None, env: Dict[str, str] | None = None,
    stdin: str | None = None,
) -> Dict[str, Any]:
    """Run an argument-vector command after a policy + risk check.

    Never uses a shell; the command is a vector, the binary is allow/deny
    checked, and the resolved risk is returned for the caller/gate to record.
    ``stdin`` (e.g. a sudo password for ``sudo -S``) is fed to the process and is
    never echoed, returned, logged, or stored in the result.
    """
    argv = [str(a) for a in argv]
    try:
        policy.check(argv)
    except (ScopeViolation, ValueError) as exc:
        return _deny(str(exc))
    risk = policy.classify(argv)
    start = time.time()
    try:
        completed = subprocess.run(  # nosec B603 - vector, no shell, policy-checked
            argv, capture_output=True, text=True, timeout=timeout, check=False,
            cwd=cwd, env=env,
            input=stdin if stdin is not None else None,
            stdin=None if stdin is not None else subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return _deny(f"command not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        return _deny(f"command timed out after {timeout}s")
    return _ok(
        command=argv,
        risk=risk.value,
        exit_code=completed.returncode,
        stdout=completed.stdout[:4000],
        stderr=completed.stderr[:2000],
        duration=round(time.time() - start, 3),
    )


# ── tool discovery ─────────────────────────────────────────────────────────

def list_tools(query: str = "", limit: int = 400) -> Dict[str, Any]:
    """List command-line tools installed on this host by scanning ``$PATH``.

    READ-only and shell-free: enumerates executables on the PATH so the agent can
    discover what it can run (and drive via ``shell_command``) instead of relying
    on a hardcoded catalog. ``query`` is a case-insensitive substring filter on
    the tool name; ``limit`` bounds the number returned.
    """
    query = (query or "").strip().lower()
    limit = max(1, min(int(limit or 400), 5000))
    path_dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    seen: Dict[str, str] = {}
    truncated = False
    for directory in path_dirs:
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for entry in entries:
                name = entry.name
                if name in seen:
                    continue
                if query and query not in name.lower():
                    continue
                try:
                    if not entry.is_file() and not entry.is_symlink():
                        continue
                    # POSIX: require the executable bit. Windows: os.access X_OK
                    # is lenient, so fall back to name membership.
                    if os.name != "nt" and not os.access(entry.path, os.X_OK):
                        continue
                except OSError:
                    continue
                seen[name] = entry.path
                if len(seen) >= limit:
                    truncated = True
                    break
        if truncated:
            break
    tools = [{"name": n, "path": p} for n, p in sorted(seen.items())]
    return _ok(tools=tools, count=len(tools), truncated=truncated, path_dirs=path_dirs)
