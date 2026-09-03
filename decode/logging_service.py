import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class LogEntry(BaseModel):
    timestamp: str
    tool: str
    user_input: str = ""
    command: str = ""
    status: str
    duration: float = 0.0
    output_file: str = ""
    error: str = ""
    metadata: dict[str, Any] = {}


class LoggingService:
    def __init__(self, base_path: Path = Path("logs")):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._ensure_tool_dirs()

    def _ensure_tool_dirs(self):
        for sub in ["planner", "memory", "skills", "audit"]:
            (self.base_path / sub).mkdir(parents=True, exist_ok=True)

    def _tool_path(self, tool: str) -> Path:
        p = self.base_path / tool
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _next_sequence(self, tool: str) -> int:
        existing = list(self._tool_path(tool).glob("*.json"))
        if not existing:
            return 1
        nums = []
        for f in existing:
            try:
                nums.append(int(f.stem.split("_")[-1]))
            except (ValueError, IndexError):
                continue
        return (max(nums) + 1) if nums else 1

    def log(self, entry: LogEntry) -> Path:
        tool_dir = self._tool_path(entry.tool)
        seq = self._next_sequence(entry.tool)
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"{today}_{seq:03d}.json"
        filepath = tool_dir / filename
        filepath.write_text(entry.model_dump_json(indent=2))
        return filepath

    def get_logs(
        self, limit: int = 20, tool_filter: str | None = None
    ) -> list[dict[str, Any]]:
        logs = []
        pattern = "*.json"
        if tool_filter:
            p = self._tool_path(tool_filter)
            if p.exists():
                files = sorted(p.glob(pattern), reverse=True)[:limit]
            else:
                files = []
        else:
            files = []
            for sub in self.base_path.iterdir():
                if sub.is_dir():
                    files.extend(sub.glob(pattern))
            files = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
        for fp in files:
            try:
                entry = json.loads(fp.read_text(encoding="utf-8"))
                logs.append(entry)
            except (json.JSONDecodeError, OSError):
                continue
        return logs

    def log_execution(
        self,
        tool: str,
        user_input: str = "",
        command: str = "",
        status: str = "success",
        duration: float = 0.0,
        output_file: str = "",
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            tool=tool,
            user_input=user_input,
            command=command,
            status=status,
            duration=duration,
            output_file=output_file,
            error=error,
            metadata=metadata or {},
        )
        return self.log(entry)
