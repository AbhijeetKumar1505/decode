"""Persistence adapter for TaskState — reuses the SQLite ``SessionStore``.

Keeps one durable source of truth: the TaskState blob is stored in the same
operational database as sessions, findings, and plans, keyed by session id.
"""

from __future__ import annotations

from ..persistence.store import SessionStore
from ..runtime.coordinator import redact_sensitive
from .task_state import TaskState


class TaskStateStore:
    def __init__(self, session_store: SessionStore) -> None:
        self._store = session_store

    def save(self, state: TaskState) -> None:
        snapshot = redact_sensitive(state.model_dump(mode="json"))
        for action in snapshot["actions"]:
            action["params"] = {}
            action["thought"] = ""
        for observation in snapshot["observations"]:
            observation["data"] = {}
            observation["summary"] = "success" if observation["success"] else "failure"
        for artifact in snapshot["artifacts"]:
            artifact["summary"] = "evidence linked"
        self._store.save_task_state(
            state.session_id, TaskState.model_validate(snapshot).model_dump_json()
        )

    def load(self, session_id: str) -> TaskState | None:
        raw = self._store.load_task_state(session_id)
        return TaskState.model_validate_json(raw) if raw else None
