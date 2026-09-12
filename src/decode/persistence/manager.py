"""Session lifecycle facade shared by the CLI/REPL and (later) the API.

Wraps the operational ``SessionStore`` so session state lives in the core rather
than the REPL: create / resolve / list / get / status, plus transcript
persistence. The transcript is a JSON array of ``{role, content}`` messages
stored next to the operational DB (``<runtime>/data/sessions/<id>.json``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..app.config import Config
from . import create_store


class SessionManager:
    def __init__(self, store: Any | None = None) -> None:
        self._store = store if store is not None else create_store()

    @property
    def store(self) -> Any:
        return self._store

    # ── lifecycle ──
    def create(self, goal: str = "", target_focus: str = "") -> str:
        return self._store.create_session(goal=goal, target_focus=target_focus)

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self._store.get_session(session_id)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._store.list_sessions(limit=limit)

    def latest(self) -> dict[str, Any] | None:
        rows = self._store.list_sessions(limit=1)
        return rows[0] if rows else None

    def resolve(
        self, resume: str | None = None, continue_last: bool = False
    ) -> str | None:
        """Pick a session id to resume at launch: an explicit id, else the latest."""
        if resume:
            return resume if self._store.get_session(resume) else None
        if continue_last:
            latest = self.latest()
            return latest["id"] if latest else None
        return None

    def close(self, session_id: str) -> None:
        self._store.close_session(session_id)

    # ── usage / cost ──
    def record_usage(
        self,
        session_id: str,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        model: str = "",
    ) -> None:
        self._store.record_usage(
            session_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            model=model,
        )

    def usage(self, session_id: str) -> dict[str, Any]:
        return self._store.get_usage(session_id)

    def reactivate(self, session_id: str) -> None:
        self._store.update_session(session_id, status="active")

    # ── transcript ──
    def transcript_dir(self) -> Path:
        return Config.MEMORY_PATH.parent / "sessions"

    def transcript_path(self, session_id: str) -> Path:
        return self.transcript_dir() / f"{session_id}.json"

    def save_transcript(
        self, session_id: str, conversation: list[dict[str, str]]
    ) -> Path:
        path = self.transcript_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(conversation, indent=2), encoding="utf-8")
        return path

    def load_transcript(self, session_id: str) -> list[dict[str, str]]:
        path = self.transcript_path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    # ── status ──
    def status(self, session_id: str) -> dict[str, Any] | None:
        session = self._store.get_session(session_id)
        if not session:
            return None
        try:
            findings = self._store.get_findings(session_id)
        except Exception:
            findings = []
        return {
            "id": session_id,
            "status": session.get("status", ""),
            "goal": session.get("goal", ""),
            "target_focus": session.get("target_focus", ""),
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at", ""),
            "findings": len(findings),
            "transcript": str(self.transcript_path(session_id)),
        }
