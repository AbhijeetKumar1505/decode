"""Policies that bound host control: filesystem scope, command risk, and modes.

Host operations do not run against IP targets, so they are governed by two
dedicated allowlists rather than ``ScopePolicy``:

* ``FilesystemScope`` — a path allowlist (separate read and write roots). Deny by
  default; every path is resolved before the check so ``..`` traversal and
  symlinks cannot escape an allowed root.
* ``CommandPolicy`` — a binary allow/deny list plus an argument-sensitive risk
  classifier, so an ad-hoc command is typed (READ/WRITE/DESTRUCTIVE) and gated
  the same way every other capability is.

``PermissionMode`` layers a Claude-Code-style autonomy dial on top of the risk
gate without ever weakening the DESTRUCTIVE control.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum
from pathlib import Path

from ..skills.base import RiskLevel


class PermissionMode(str, Enum):
    PLAN = "plan"  # never execute; only describe what would run
    ASK = "ask"  # default: READ auto, WRITE/DESTRUCTIVE need approval
    AUTO = "auto"  # READ + WRITE auto within scope; DESTRUCTIVE still gated


class ScopeViolation(PermissionError):
    """Raised when a path or command falls outside its allowlist."""


class FilesystemScope:
    """A resolved-path allowlist with separate read and write roots."""

    def __init__(
        self,
        read_roots: Iterable[str | Path] | None = None,
        write_roots: Iterable[str | Path] | None = None,
    ) -> None:
        self._read_roots = self._resolve_roots(read_roots)
        # write roots are implicitly readable
        self._write_roots = self._resolve_roots(write_roots)

    @staticmethod
    def _resolve_roots(roots: Iterable[str | Path] | None) -> list[Path]:
        resolved: list[Path] = []
        for root in roots or []:
            try:
                resolved.append(Path(root).expanduser().resolve(strict=False))
            except OSError:
                continue
        return resolved

    @staticmethod
    def _within(path: Path, roots: Sequence[Path]) -> bool:
        try:
            resolved = path.expanduser().resolve(strict=False)
        except OSError:
            return False
        for root in roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def allows(self, path: str | Path, *, write: bool = False) -> bool:
        candidate = Path(path)
        if write:
            return self._within(candidate, self._write_roots)
        return self._within(candidate, self._read_roots) or self._within(
            candidate, self._write_roots
        )

    def check(self, path: str | Path, *, write: bool = False) -> None:
        if not self.allows(path, write=write):
            kind = "write" if write else "read"
            raise ScopeViolation(
                f"path '{path}' is outside the authorized {kind} scope"
            )

    @property
    def is_empty(self) -> bool:
        return not self._read_roots and not self._write_roots

    @property
    def read_roots(self) -> list[str]:
        """Resolved read-root paths as strings (write roots are implicitly readable)."""
        return [str(root) for root in self._read_roots]

    @property
    def write_roots(self) -> list[str]:
        """Resolved write-root paths as strings."""
        return [str(root) for root in self._write_roots]


# Argument-sensitive command risk. Presence of any token classifies upward.
_DESTRUCTIVE_BINARIES = frozenset(
    {
        "rm",
        "rmdir",
        "dd",
        "mkfs",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "kill",
        "pkill",
        "killall",
        "shred",
        "fdisk",
        "parted",
        "wipefs",
        "userdel",
    }
)
_WRITE_BINARIES = frozenset(
    {
        "mv",
        "cp",
        "tee",
        "chmod",
        "chown",
        "ln",
        "touch",
        "mkdir",
        "install",
        "apt",
        "apt-get",
        "pip",
        "pip3",
        "npm",
        "systemctl",
        "service",
        "sed",
        "truncate",
        "git",
    }
)
_DESTRUCTIVE_TOKENS = ("--force", "-rf", "-fr", "--no-preserve-root")

# sudo flags that consume the following token as a value; used to find the real
# command after a leading `sudo ...`.
_SUDO_VALUE_FLAGS = frozenset(
    {
        "-u",
        "--user",
        "-g",
        "--group",
        "-p",
        "--prompt",
        "-C",
        "--close-from",
        "-h",
        "--host",
        "-R",
        "--chroot",
        "-D",
        "--chdir",
        "-T",
        "--command-timeout",
        "-r",
        "--role",
        "-t",
        "--type",
    }
)


def strip_sudo(argv: Sequence[str]) -> tuple[bool, list[str]]:
    """Return (is_sudo, inner_argv). Skips sudo's own options to find the command.

    ``sudo -S apt install nmap`` -> (True, ["apt", "install", "nmap"]).
    """
    if not argv or Path(str(argv[0])).name != "sudo":
        return False, [str(a) for a in argv]
    i = 1
    while i < len(argv):
        tok = str(argv[i])
        if tok == "--":
            i += 1
            break
        if tok.startswith("-"):
            i += 2 if tok in _SUDO_VALUE_FLAGS else 1
        else:
            break
    return True, [str(a) for a in argv[i:]]


class CommandPolicy:
    """Binary allow/deny plus argument-sensitive risk classification."""

    def __init__(
        self,
        allowed_binaries: Iterable[str] | None = None,
        denied_binaries: Iterable[str] | None = None,
    ) -> None:
        self._allowed = set(allowed_binaries) if allowed_binaries is not None else None
        self._denied = set(denied_binaries or set())

    def _binary(self, argv: Sequence[str]) -> str:
        if not argv:
            raise ValueError("empty command")
        return Path(str(argv[0])).name

    def is_allowed(self, argv: Sequence[str]) -> bool:
        binary = self._binary(argv)
        if binary in self._denied:
            return False
        return not (self._allowed is not None and binary not in self._allowed)

    def check(self, argv: Sequence[str]) -> None:
        if not self.is_allowed(argv):
            raise ScopeViolation(f"command '{self._binary(argv)}' is not permitted")

    def classify(self, argv: Sequence[str]) -> RiskLevel:
        # A leading `sudo` is privilege escalation: classify the wrapped command,
        # but never rank it below WRITE.
        is_sudo, inner = strip_sudo(argv)
        target = inner if is_sudo else [str(a) for a in argv]
        if not target:
            return RiskLevel.WRITE if is_sudo else RiskLevel.READ
        binary = Path(str(target[0])).name
        tokens = {str(a).lower() for a in target[1:]}
        if binary in _DESTRUCTIVE_BINARIES or any(
            t in tokens for t in _DESTRUCTIVE_TOKENS
        ):
            return RiskLevel.DESTRUCTIVE
        if any(str(a).startswith(">") for a in target):  # output redirection
            return RiskLevel.DESTRUCTIVE
        base = RiskLevel.WRITE if binary in _WRITE_BINARIES else RiskLevel.READ
        if is_sudo and base is RiskLevel.READ:
            return RiskLevel.WRITE
        return base


def resolve_mode_decision(mode: PermissionMode, risk: RiskLevel) -> str:
    """Return 'allow', 'approve', or 'deny' for a mode+risk, before the gate.

    Never returns 'allow' for DESTRUCTIVE. PLAN denies all execution.
    """
    if mode is PermissionMode.PLAN:
        return "deny"
    if risk is RiskLevel.READ:
        return "allow"
    if risk is RiskLevel.DESTRUCTIVE:
        return "approve"
    # WRITE
    return "allow" if mode is PermissionMode.AUTO else "approve"
