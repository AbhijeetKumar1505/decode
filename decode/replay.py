"""Replay metadata for reproducible capability execution.

A replay record binds the exact material command and the full tool/adapter/
parser/environment identity to the hash of the evidence it produced. It is the
reproducibility unit for P5: two runs of the same capability in documented
environments should yield the same replay identity and equivalent normalized
results. Replay records may contain scoped parameters (targets, ports) and are
handled like evidence — protected and redacted where rendered.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from pydantic import BaseModel, Field

REPLAY_SCHEMA_VERSION = "1.0.0"


class ReplayRecord(BaseModel):
    schema_version: str = REPLAY_SCHEMA_VERSION
    replay_id: str = ""
    capability: str = ""
    tool: str = ""
    tool_version: str = ""
    argv: List[str] = Field(default_factory=list)
    normalized_params: Dict[str, Any] = Field(default_factory=dict)
    adapter_id: str = ""
    adapter_version: str = ""
    parser_id: str = ""
    parser_version: str = ""
    executor: str = ""
    platform: str = ""
    architecture: str = ""
    environment_version: str = ""
    evidence_id: str = ""
    evidence_sha256: str = ""
    created_at: str = ""

    @property
    def command(self) -> str:
        import shlex

        return shlex.join(self.argv)


def _stable_replay_id(fields: Dict[str, Any]) -> str:
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_replay_record(
    invocation: Any,
    *,
    tool_version: str = "",
    executor: str = "",
    platform: str = "",
    architecture: str = "",
    environment_version: str = "",
    evidence_id: str = "",
    evidence_sha256: str = "",
) -> ReplayRecord:
    """Assemble a replay record from an adapter invocation and its evidence hash.

    ``replay_id`` is a stable hash over the material command and execution
    identity (excluding volatile fields like timestamps and the evidence hash),
    so the same capability run in an equivalent environment reproduces the id.
    """
    identity = {
        "capability": invocation.capability,
        "tool": invocation.tool,
        "tool_version": tool_version,
        "argv": list(invocation.argv),
        "adapter_id": invocation.adapter_id,
        "adapter_version": invocation.adapter_version,
        "parser_id": invocation.parser_id,
        "parser_version": invocation.parser_version,
        "executor": executor,
        "platform": platform,
        "architecture": architecture,
        "environment_version": environment_version,
    }
    return ReplayRecord(
        replay_id=_stable_replay_id(identity),
        capability=invocation.capability,
        tool=invocation.tool,
        tool_version=tool_version,
        argv=list(invocation.argv),
        normalized_params=dict(invocation.normalized_params),
        adapter_id=invocation.adapter_id,
        adapter_version=invocation.adapter_version,
        parser_id=invocation.parser_id,
        parser_version=invocation.parser_version,
        executor=executor,
        platform=platform,
        architecture=architecture,
        environment_version=environment_version,
        evidence_id=evidence_id,
        evidence_sha256=evidence_sha256,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
