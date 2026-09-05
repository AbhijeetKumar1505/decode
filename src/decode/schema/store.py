"""Persistence adapter for TaskState — reuses the SQLite ``SessionStore``.

Keeps one durable source of truth: the TaskState blob is stored in the same
operational database as sessions, findings, and plans, keyed by session id.
"""

from __future__ import annotations

from ..persistence.store import SessionStore
from .task_state import TaskState


class TaskStateStore:
    def __init__(self, session_store: SessionStore) -> None:
        self._store = session_store

    def save(self, state: TaskState) -> None:
        self._store.save_task_state(state.session_id, state.model_dump_json())

    def load(self, session_id: str) -> TaskState | None:
        raw = self._store.load_task_state(session_id)
        return TaskState.model_validate_json(raw) if raw else None
