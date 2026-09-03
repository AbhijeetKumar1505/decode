from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ContextEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionState(BaseModel):
    goal: str = ""
    workflow_id: str | None = None
    current_step: str | None = None
    executed_skills: list[dict[str, Any]] = Field(default_factory=list)
    skill_outputs: dict[str, Any] = Field(default_factory=dict)


class ContextManager:
    def __init__(self):
        self._session = SessionState()
        self._history: list[ContextEntry] = []

    def set_goal(self, goal: str):
        self._session.goal = goal
        self._session.workflow_id = None
        self._session.current_step = None
        self._session.executed_skills.clear()
        self._session.skill_outputs.clear()

    def get_goal(self) -> str:
        return self._session.goal

    def add_entry(
        self, role: str, content: str, metadata: dict[str, Any] | None = None
    ):
        self._history.append(
            ContextEntry(role=role, content=content, metadata=metadata or {})
        )

    def record_skill_execution(
        self, skill_name: str, params: dict[str, Any], result: dict[str, Any]
    ):
        self._session.executed_skills.append(
            {
                "skill": skill_name,
                "params": params,
                "result": result,
            }
        )
        self._session.skill_outputs[skill_name] = result

    def get_recent_history(self, n: int = 10) -> list[ContextEntry]:
        return self._history[-n:]

    def get_session_summary(self) -> dict[str, Any]:
        return {
            "goal": self._session.goal,
            "executed_skills": len(self._session.executed_skills),
            "skill_outputs": list(self._session.skill_outputs.keys()),
            "history_length": len(self._history),
        }

    def format_context(self, n_history: int = 5) -> str:
        lines = [f"Goal: {self._session.goal}"]
        if self._session.executed_skills:
            lines.append(f"Executed: {len(self._session.executed_skills)} skills")
            for s in self._session.executed_skills[-3:]:
                lines.append(f"  - {s['skill']}: {str(s['result'])[:100]}")
        recent = self.get_recent_history(n_history)
        for entry in recent:
            prefix = "User" if entry.role == "user" else "Agent"
            lines.append(f"[{prefix}] {entry.content[:200]}")
        return "\n".join(lines)
