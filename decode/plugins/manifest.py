"""Versioned, non-executing plugin manifest discovery for the P2 trust boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import __version__


PLUGIN_MANIFEST_SCHEMA_VERSION = "1.0.0"
_PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_ENTRYPOINT_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONSTRAINT_PATTERN = re.compile(r"^(>=|<=|==|>|<)(\d+(?:\.\d+){0,2})$")


class PluginRiskLevel(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class PluginSandboxProfile(str, Enum):
    TRUSTED_IN_PROCESS = "trusted_in_process"
    RESTRICTED_SUBPROCESS = "restricted_subprocess"
    CONTAINER = "container"


class PluginState(str, Enum):
    VERIFIED = "verified"
    DISABLED = "disabled"
    FAILED = "failed"
    REVOKED = "revoked"


class PluginCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    risk: PluginRiskLevel

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _PLUGIN_ID_PATTERN.fullmatch(value):
            raise ValueError("capability id must use lowercase dotted, dashed, or underscored segments")
        return value


class PluginDependencies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)

    @field_validator("python", "tools")
    @classmethod
    def validate_dependencies(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or "\x00" in value for value in values):
            raise ValueError("dependency names must be non-empty and cannot contain NUL bytes")
        return list(dict.fromkeys(values))


class PluginPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: str = Field(default="none", pattern=r"^(none|scoped_targets)$")
    memory_read: list[str] = Field(default_factory=list)
    memory_write: list[str] = Field(default_factory=list)
    filesystem_read: list[str] = Field(default_factory=list)
    filesystem_write: list[str] = Field(default_factory=list)
    secrets: bool = False
    models: bool = False

    @field_validator(
        "memory_read",
        "memory_write",
        "filesystem_read",
        "filesystem_write",
    )
    @classmethod
    def validate_scopes(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or "\x00" in value for value in values):
            raise ValueError("permission scopes must be non-empty and cannot contain NUL bytes")
        return list(dict.fromkeys(values))


class PluginManifest(BaseModel):
    """A declaration of requested plugin capabilities, never a permission grant."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PLUGIN_MANIFEST_SCHEMA_VERSION
    id: str = Field(min_length=3, max_length=128)
    version: str
    entrypoint: str
    decode: str = Field(min_length=1, max_length=128)
    source_digest: str
    capabilities: list[PluginCapability] = Field(min_length=1)
    permissions: PluginPermissions = Field(default_factory=PluginPermissions)
    dependencies: PluginDependencies = Field(default_factory=PluginDependencies)
    platforms: list[str] = Field(default_factory=list)
    sandbox: PluginSandboxProfile = PluginSandboxProfile.RESTRICTED_SUBPROCESS

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != PLUGIN_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported plugin manifest schema version: {value}"
            )
        return value

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _PLUGIN_ID_PATTERN.fullmatch(value):
            raise ValueError("plugin id must use lowercase dotted, dashed, or underscored segments")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not _SEMVER_PATTERN.fullmatch(value):
            raise ValueError("plugin version must use MAJOR.MINOR.PATCH")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        if not _ENTRYPOINT_PATTERN.fullmatch(value):
            raise ValueError("entrypoint must use module.path:callable syntax")
        return value

    @field_validator("decode")
    @classmethod
    def validate_decode_constraint(cls, value: str) -> str:
        constraints = [part.strip() for part in value.split(",") if part.strip()]
        if not constraints or any(
            not _CONSTRAINT_PATTERN.fullmatch(constraint)
            for constraint in constraints
        ):
            raise ValueError("decode must contain comma-separated semantic version constraints")
        return ",".join(constraints)

    @field_validator("source_digest")
    @classmethod
    def validate_source_digest(cls, value: str) -> str:
        if not _DIGEST_PATTERN.fullmatch(value):
            raise ValueError("source_digest must be a lowercase sha256 digest")
        return value

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, values: list[str]) -> list[str]:
        normalized = [value.lower() for value in values]
        if any(value not in {"windows", "linux", "darwin"} for value in normalized):
            raise ValueError("platforms must contain windows, linux, or darwin")
        return list(dict.fromkeys(normalized))

    def entrypoint_path(self, plugin_root: Path) -> Path:
        module, _, _ = self.entrypoint.partition(":")
        source_path = plugin_root.joinpath(*module.split(".")).with_suffix(".py")
        resolved_root = plugin_root.resolve()
        resolved_source = source_path.resolve()
        if resolved_root not in resolved_source.parents:
            raise ValueError("entrypoint resolves outside the plugin root")
        return resolved_source

    def supports_decode(self, version: str = __version__) -> bool:
        candidate = _version_tuple(version)
        for constraint in self.decode.split(","):
            match = _CONSTRAINT_PATTERN.fullmatch(constraint)
            if match is None:
                return False
            operator, expected_text = match.groups()
            expected = _version_tuple(expected_text)
            if not _compare_versions(candidate, operator, expected):
                return False
        return True


class PluginManifestRecord(BaseModel):
    """The safe result of discovery; no entrypoint is imported to create it."""

    manifest_path: Path
    manifest: PluginManifest | None = None
    state: PluginState
    reason: str = ""
    source_verified: bool = False


class PluginManifestRegistry:
    """Discover manifest packages without importing or executing plugin code."""

    def __init__(
        self,
        root: Path,
        revoked_ids: set[str] | None = None,
    ) -> None:
        self._root = root
        self._revoked_ids = set(revoked_ids or set())
        self._records: dict[str, PluginManifestRecord] = {}

    def discover(self) -> list[PluginManifestRecord]:
        self._records = {}
        if not self._root.is_dir():
            return []
        for manifest_path in sorted(self._root.glob("*/plugin.json")):
            record = self._read_record(manifest_path)
            key = record.manifest.id if record.manifest is not None else manifest_path.parent.name
            if key in self._records:
                record.state = PluginState.FAILED
                record.reason = f"duplicate plugin id: {key}"
                key = f"{key}@{manifest_path.parent.name}"
            self._records[key] = record
        return self.records()

    def records(self) -> list[PluginManifestRecord]:
        return list(self._records.values())

    def get(self, plugin_id: str) -> PluginManifestRecord | None:
        return self._records.get(plugin_id)

    def disable(self, plugin_id: str) -> PluginManifestRecord:
        record = self.get(plugin_id)
        if record is None:
            raise ValueError(f"plugin manifest not found: {plugin_id}")
        if record.state == PluginState.REVOKED:
            raise ValueError(f"plugin manifest is revoked: {plugin_id}")
        record.state = PluginState.DISABLED
        record.reason = "disabled by local policy"
        return record

    def _read_record(self, manifest_path: Path) -> PluginManifestRecord:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = PluginManifest.model_validate(payload)
        except (OSError, ValueError) as exc:
            return PluginManifestRecord(
                manifest_path=manifest_path,
                state=PluginState.FAILED,
                reason=f"invalid manifest: {exc}",
            )

        if manifest.id in self._revoked_ids:
            return PluginManifestRecord(
                manifest_path=manifest_path,
                manifest=manifest,
                state=PluginState.REVOKED,
                reason="plugin id is revoked by local policy",
            )
        if not manifest.supports_decode():
            return PluginManifestRecord(
                manifest_path=manifest_path,
                manifest=manifest,
                state=PluginState.FAILED,
                reason=f"plugin is incompatible with Decode {__version__}",
            )
        try:
            source_path = manifest.entrypoint_path(manifest_path.parent)
            actual_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            return PluginManifestRecord(
                manifest_path=manifest_path,
                manifest=manifest,
                state=PluginState.FAILED,
                reason=f"entrypoint verification failed: {exc}",
            )
        expected_digest = manifest.source_digest.removeprefix("sha256:")
        if not hmac.compare_digest(actual_digest, expected_digest):
            return PluginManifestRecord(
                manifest_path=manifest_path,
                manifest=manifest,
                state=PluginState.FAILED,
                reason="entrypoint digest does not match source_digest",
            )
        return PluginManifestRecord(
            manifest_path=manifest_path,
            manifest=manifest,
            state=PluginState.VERIFIED,
            source_verified=True,
        )


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in value.split(".")]
    return tuple((parts + [0, 0, 0])[:3])


def _compare_versions(
    candidate: tuple[int, int, int],
    operator: str,
    expected: tuple[int, int, int],
) -> bool:
    comparisons: dict[str, bool] = {
        ">=": candidate >= expected,
        "<=": candidate <= expected,
        "==": candidate == expected,
        ">": candidate > expected,
        "<": candidate < expected,
    }
    return comparisons[operator]
