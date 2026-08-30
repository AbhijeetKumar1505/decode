"""Configuration scopes for the extension layer.

Three scopes, lowest-to-highest precedence: system, user, project. A project can
override user settings, which override system settings, without touching the
others. Paths are resolved lazily so tests and non-standard installs can redirect
them via environment variables.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import List, Optional


class Scope(str, Enum):
    SYSTEM = "system"
    USER = "user"
    PROJECT = "project"


#: Merge order: later scopes override earlier ones.
PRECEDENCE: List[Scope] = [Scope.SYSTEM, Scope.USER, Scope.PROJECT]


def user_root() -> Path:
    """User scope: ``$DECODE_HOME`` or ``~/.decode``."""
    override = os.environ.get("DECODE_HOME")
    return Path(override) if override else (Path.home() / ".decode")


def project_root(start: Optional[Path] = None) -> Path:
    """Project scope: the nearest ancestor ``.decode`` dir, else ``<cwd>/.decode``.

    Honors ``$DECODE_PROJECT_HOME`` for tests and explicit overrides.
    """
    override = os.environ.get("DECODE_PROJECT_HOME")
    if override:
        return Path(override)
    origin = (start or Path.cwd()).resolve()
    for directory in [origin, *origin.parents]:
        candidate = directory / ".decode"
        if candidate.is_dir():
            return candidate
    return origin / ".decode"


def system_root() -> Optional[Path]:
    """System scope: ``$DECODE_SYSTEM_HOME`` or ``/etc/decode`` on POSIX; None on Windows."""
    override = os.environ.get("DECODE_SYSTEM_HOME")
    if override:
        return Path(override)
    if os.name == "posix":
        return Path("/etc/decode")
    return None


def scope_root(scope: Scope) -> Optional[Path]:
    if scope is Scope.USER:
        return user_root()
    if scope is Scope.PROJECT:
        return project_root()
    return system_root()


def ensure_scope(scope: Scope) -> Path:
    """Return the scope root, creating it if necessary. Raises for an unavailable
    scope (e.g. system scope on Windows)."""
    root = scope_root(scope)
    if root is None:
        raise ValueError(f"{scope.value} scope is not available on this platform")
    root.mkdir(parents=True, exist_ok=True)
    return root
