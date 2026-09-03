import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ExecutionFeedback(BaseModel):
    skill: str
    success: bool
    execution_time: float = 0.0
    dependency_missing: bool = False
    error: str = ""
    metadata: dict[str, Any] = {}


class DependencyFeedback(BaseModel):
    tool: str
    missing: bool
    install_command: str = ""
    attempt_install: bool = False
    install_success: bool = False


class AgentDecisionFeedback(BaseModel):
    planner: str
    confidence: float = 0.0
    alternatives: list[str] = []
    execution_time: float = 0.0
    success: bool = True


class FeedbackStore:
    def __init__(self, base_path: Path = Path("feedback")):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._exec_log = base_path / "execution.jsonl"
        self._dep_log = base_path / "dependencies.jsonl"
        self._decision_log = base_path / "decisions.jsonl"

    def record_execution(self, feedback: ExecutionFeedback) -> str:
        entry = feedback.model_dump()
        entry["id"] = str(uuid.uuid4())
        entry["timestamp"] = datetime.now().isoformat()
        line = json.dumps(entry) + "\n"
        with open(self._exec_log, "a", encoding="utf-8") as f:
            f.write(line)
        return entry["id"]

    def record_dependency(self, feedback: DependencyFeedback) -> str:
        entry = feedback.model_dump()
        entry["id"] = str(uuid.uuid4())
        entry["timestamp"] = datetime.now().isoformat()
        line = json.dumps(entry) + "\n"
        with open(self._dep_log, "a", encoding="utf-8") as f:
            f.write(line)
        return entry["id"]

    def record_decision(self, feedback: AgentDecisionFeedback) -> str:
        entry = feedback.model_dump()
        entry["id"] = str(uuid.uuid4())
        entry["timestamp"] = datetime.now().isoformat()
        line = json.dumps(entry) + "\n"
        with open(self._decision_log, "a", encoding="utf-8") as f:
            f.write(line)
        return entry["id"]

    def get_execution_feedback(self, skill: str | None = None) -> list[dict[str, Any]]:
        return self._query_log(
            self._exec_log, lambda e: not skill or e.get("skill") == skill
        )

    def get_dependency_feedback(self) -> list[dict[str, Any]]:
        return self._query_log(self._dep_log)

    def get_decision_feedback(self) -> list[dict[str, Any]]:
        return self._query_log(self._decision_log)

    def _query_log(self, path: Path, filter_fn=None) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        results = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if filter_fn and not filter_fn(entry):
                        continue
                    results.append(entry)
                except json.JSONDecodeError:
                    continue
        return results
