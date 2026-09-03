import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

EVENT_TYPES = [
    "tool_execution",
    "approval",
    "rejection",
    "error",
    "skill_load",
    "plugin_load",
    "system_startup",
    "system_shutdown",
]


class AuditEvent(BaseModel):
    id: str = ""
    timestamp: str
    event: str
    tool: str = ""
    target: str = ""
    risk: str = ""
    approved: bool = False
    user: str = ""
    detail: str = ""
    metadata: dict[str, Any] = {}


class AuditLayer:
    def __init__(self, base_path: Path = Path("audit")):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._current_log = (
            self.base_path / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        )

    def _rotate(self):
        today = f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        if self._current_log.name != today:
            self._current_log = self.base_path / today

    def record(self, event: AuditEvent) -> str:
        self._rotate()
        if not event.id:
            event.id = str(uuid.uuid4())
        if not event.timestamp:
            event.timestamp = datetime.now().isoformat()
        line = event.model_dump_json() + "\n"
        with open(self._current_log, "a", encoding="utf-8") as f:
            f.write(line)
        return event.id

    def record_execution(
        self,
        tool: str,
        target: str = "",
        risk: str = "unknown",
        approved: bool = True,
        user: str = "",
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.record(
            AuditEvent(
                timestamp=datetime.now().isoformat(),
                event="tool_execution",
                tool=tool,
                target=target,
                risk=risk,
                approved=approved,
                user=user,
                detail=detail,
                metadata=metadata or {},
            )
        )

    def query(
        self, date: str | None = None, event_type: str | None = None
    ) -> list[AuditEvent]:
        log_file = (
            self.base_path / f"{date or datetime.now().strftime('%Y-%m-%d')}.jsonl"
        )
        if not log_file.exists():
            return []
        results = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = AuditEvent(**json.loads(line))
                    if event_type and ev.event != event_type:
                        continue
                    results.append(ev)
                except (json.JSONDecodeError, Exception):
                    continue
        return results
