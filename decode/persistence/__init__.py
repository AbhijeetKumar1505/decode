import os
from typing import Any

from .store import SessionStore
from .target_tracker import TargetContextTracker, TargetFinding
from .evidence import EvidenceCollector, Evidence


def create_store(**kwargs: Any):
    """Return the configured operational store.

    Uses MongoDB when ``MONGODB_URI`` is set, otherwise the local SQLite store.
    A configured-but-unreachable MongoDB warns and falls back to local SQLite so
    the app still starts; the warning makes the downgrade visible rather than
    silent, and unsetting ``MONGODB_URI`` selects SQLite outright.
    """
    if os.getenv("MONGODB_URI"):
        from .mongo_store import MongoSessionStore

        try:
            return MongoSessionStore(**kwargs)
        except Exception as exc:  # unreachable cluster, TLS, auth, DNS, ...
            import sys

            print(
                f"[decode] MongoDB backend unavailable ({type(exc).__name__}); "
                "falling back to local SQLite. Unset MONGODB_URI to silence this.",
                file=sys.stderr,
            )
            return SessionStore()
    return SessionStore(**kwargs)


__all__ = [
    "SessionStore",
    "create_store",
    "TargetContextTracker",
    "TargetFinding",
    "EvidenceCollector",
    "Evidence",
]
