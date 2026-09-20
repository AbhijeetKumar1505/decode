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

import ipaddress
import re
from collections.abc import Iterable, Sequence
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

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
_SHELL_CONTROL_TOKENS = frozenset(
    {"|", "||", "&&", ";", "&", "<", ">", ">>", "1>", "1>>", "2>", "2>>"}
)
_SHELL_INTERPRETERS = frozenset(
    {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "pwsh"}
)
_NETWORK_BINARIES = frozenset(
    {
        "amass",
        "chromium",
        "chromium-browser",
        "curl",
        "dig",
        "ffuf",
        "firefox",
        "gobuster",
        "google-chrome",
        "host",
        "httpx",
        "links",
        "lynx",
        "naabu",
        "nc",
        "ncat",
        "netcat",
        "nikto",
        "nmap",
        "nslookup",
        "nuclei",
        "rsync",
        "scp",
        "sftp",
        "sqlmap",
        "ssh",
        "subfinder",
        "telnet",
        "w3m",
        "wget",
    }
)
_DIAGNOSTIC_FLAGS = frozenset({"--help", "--version"})
_DOMAIN_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?::\d{1,5})?$",
    re.IGNORECASE,
)

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


def command_output_paths(
    argv: Sequence[str], *, cwd: str | Path | None = None
) -> list[Path]:
    """Return explicit filesystem outputs declared by a command vector."""
    _is_sudo, inner = strip_sudo(argv)
    if not inner:
        return []
    binary = Path(str(inner[0])).name.lower()
    args = [str(value) for value in inner[1:]]
    raw_paths: list[str] = []
    value_flags = {"--output", "--output-file"}
    prefix_flags = ("--output=", "--output-file=")
    if binary == "curl":
        value_flags.update({"-o", "--output-dir"})
        prefix_flags += ("--output-dir=",)
    elif binary == "wget":
        value_flags.update({"-O", "--output-document", "-P", "--directory-prefix"})
        prefix_flags += ("--output-document=", "--directory-prefix=")
    else:
        value_flags.add("-o")

    index = 0
    while index < len(args):
        token = args[index]
        if token in value_flags and index + 1 < len(args):
            raw_paths.append(args[index + 1])
            index += 2
            continue
        matched = next((prefix for prefix in prefix_flags if token.startswith(prefix)), None)
        if matched is not None and token[len(matched) :]:
            raw_paths.append(token[len(matched) :])
        if binary == "curl" and token == "-O":
            raw_paths.append(str(cwd or Path.cwd()))
        if binary == "curl" and token.startswith("-o") and token != "-o":
            raw_paths.append(token[2:])
        if binary == "nmap" and token[:3] in {"-oN", "-oX", "-oG", "-oA"}:
            if len(token) > 3:
                raw_paths.append(token[3:])
            elif index + 1 < len(args):
                raw_paths.append(args[index + 1])
                index += 1
        index += 1

    positional = [value for value in args if value and not value.startswith("-")]
    if binary in {"cp", "mv", "install"} and positional:
        raw_paths.append(positional[-1])
    elif binary in {"touch", "mkdir", "tee"}:
        raw_paths.extend(positional)

    base = Path(cwd or Path.cwd()).expanduser().resolve(strict=False)
    resolved: list[Path] = []
    for value in raw_paths:
        candidate = Path(value).expanduser()
        path = candidate if candidate.is_absolute() else base / candidate
        normalized = path.resolve(strict=False)
        if normalized not in resolved:
            resolved.append(normalized)
    return resolved


def command_target(argv: Sequence[str]) -> str:
    """Return a recognizable network target carried by an argument vector."""
    _is_sudo, inner = strip_sudo(argv)
    if not inner:
        return ""
    binary = Path(str(inner[0])).name.lower()
    for raw in inner[1:]:
        value = str(raw).strip().strip("'\"")
        if not value or value.startswith("-"):
            continue
        if "://" in value:
            parsed = urlparse(value)
            if parsed.hostname:
                return value
        candidate = value.strip("[](),;")
        try:
            ipaddress.ip_network(candidate, strict=False)
            return candidate
        except ValueError:
            pass
        if binary in _NETWORK_BINARIES and _DOMAIN_PATTERN.fullmatch(candidate):
            return candidate
    return ""


def command_requires_target(argv: Sequence[str]) -> bool:
    """Whether this command may perform network I/O against a target."""
    _is_sudo, inner = strip_sudo(argv)
    if not inner:
        return False
    binary = Path(str(inner[0])).name.lower()
    flags = {str(value) for value in inner[1:]}
    if binary in _NETWORK_BINARIES and flags & _DIAGNOSTIC_FLAGS:
        return False
    return bool(command_target(inner)) or binary in _NETWORK_BINARIES


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
        _is_sudo, inner = strip_sudo(argv)
        if not inner:
            return
        binary = Path(str(inner[0])).name.lower()
        lowered = [str(value).lower() for value in inner[1:]]
        if binary in _SHELL_INTERPRETERS and any(
            value in {"-c", "/c", "-command", "-encodedcommand"}
            for value in lowered
        ):
            raise ScopeViolation(
                "shell interpreter command strings are not permitted; use an argument vector"
            )
        for token in (str(value) for value in inner):
            if (
                token in _SHELL_CONTROL_TOKENS
                or token.startswith((">", "1>", "2>", "<(", ">("))
                or "$(" in token
                or "`" in token
            ):
                raise ScopeViolation(
                    f"shell operator '{token}' is not permitted in argument-vector mode"
                )

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
        if command_output_paths(target):
            return RiskLevel.WRITE
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
