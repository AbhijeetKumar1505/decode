"""Persistence adapter for TaskState — reuses the SQLite ``SessionStore``.

Keeps one durable source of truth: the TaskState blob is stored in the same
operational database as sessions, findings, and plans, keyed by session id.
"""

from __future__ import annotations

import json

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
        if not raw:
            return None
        payload = json.loads(raw)
        active_nodes = (
            payload.get("active_nodes", {}) if isinstance(payload, dict) else {}
        )
        for active in active_nodes.values() if isinstance(active_nodes, dict) else ():
            if (
                isinstance(active, dict)
                and active.get("outcome") != "completed"
                and "escalation" not in active
            ):
                active["escalation"] = {"kind": "legacy_unclassified"}
        return TaskState.model_validate(payload)
