import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    path: str
    sha256: str
    size_bytes: int
    mime_type: str
    created_at: str


class ProtectedEvidenceStore:
    def __init__(self, base_path: Path = Path("evidence")) -> None:
        self.base_path = base_path

    def capture(
        self,
        data: Any,
        *,
        evidence_id: str = "",
    ) -> EvidenceReference:
        payload, mime_type = self._serialize(data)
        digest = hashlib.sha256(payload).hexdigest()
        identifier = evidence_id or str(uuid4())
        if not identifier.replace("-", "").isalnum():
            raise ValueError(
                "evidence_id must contain only letters, numbers, or hyphens"
            )

        self._ensure_root()
        path = self.base_path / f"{identifier}.evidence"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("protected evidence path must be a regular file")
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise RuntimeError(
                    "immutable evidence path already contains other data"
                )
            path.chmod(0o600)
        else:
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                path.chmod(0o600)
            except Exception:
                path.unlink(missing_ok=True)
                raise

        return EvidenceReference(
            id=identifier,
            path=str(path),
            sha256=digest,
            size_bytes=len(payload),
            mime_type=mime_type,
            created_at=datetime.now(UTC).isoformat(),
        )

    def verify(self, reference: EvidenceReference) -> bool:
        path = Path(reference.path)
        expected_path = self.base_path / f"{reference.id}.evidence"
        if path.resolve(strict=False) != expected_path.resolve(strict=False):
            return False
        if path.is_symlink() or not path.is_file():
            return False
        try:
            payload = path.read_bytes()
        except OSError:
            return False
        return (
            len(payload) == reference.size_bytes
            and hashlib.sha256(payload).hexdigest() == reference.sha256
        )

    def _ensure_root(self) -> None:
        if self.base_path.exists() and self.base_path.is_symlink():
            raise RuntimeError("protected evidence root cannot be a symbolic link")
        self.base_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.base_path.chmod(0o700)

    @staticmethod
    def _serialize(data: Any) -> tuple[bytes, str]:
        if isinstance(data, bytes):
            return data, "application/octet-stream"
        if isinstance(data, str):
            return data.encode("utf-8"), "text/plain"
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        payload = json.dumps(
            data,
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return payload, "application/json"


class Evidence:
    def __init__(
        self,
        type: str,
        label: str,
        reference: EvidenceReference,
        source: str = "",
    ) -> None:
        self.id = str(uuid4())
        self.type = type
        self.label = label
        self.reference = reference
        self.data = reference.model_dump()
        self.source = source
        self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
        }


class EvidenceCollector:
    def __init__(self, base_path: Path = Path("evidence")) -> None:
        self._evidence: list[Evidence] = []
        self._store = ProtectedEvidenceStore(base_path)

    def collect(
        self, type: str, label: str, data: dict[str, Any], source: str = ""
    ) -> Evidence:
        reference = self._store.capture(data)
        ev = Evidence(type, label, reference, source)
        self._evidence.append(ev)
        return ev

    def collect_command_output(
        self,
        command: str,
        stdout: str,
        stderr: str = "",
        exit_code: int = 0,
        source: str = "",
    ) -> Evidence:
        return self.collect(
            type="command_output",
            label=f"Command: {command[:80]}",
            data={
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
            },
            source=source,
        )

    def collect_scan_result(
        self, scanner: str, target: str, raw: str, parsed: dict | None = None
    ) -> Evidence:
        return self.collect(
            type="scan_result",
            label=f"{scanner} scan of {target}",
            data={
                "scanner": scanner,
                "target": target,
                "raw_output": raw,
                "parsed": parsed or {},
            },
            source=scanner,
        )

    def collect_finding(
        self, title: str, description: str, severity: str, detail: dict | None = None
    ) -> Evidence:
        return self.collect(
            type="finding",
            label=title,
            data={
                "title": title,
                "description": description,
                "severity": severity,
                "detail": detail or {},
            },
            source="analyzer",
        )

    def get_all(self) -> list[Evidence]:
        return list(self._evidence)

    def get_by_type(self, type: str) -> list[Evidence]:
        return [e for e in self._evidence if e.type == type]

    def get_by_source(self, source: str) -> list[Evidence]:
        return [e for e in self._evidence if e.source == source]

    def clear(self):
        self._evidence.clear()
