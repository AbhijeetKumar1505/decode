"""Persisted lifecycle and static conformance checks for manifest plugins."""

from __future__ import annotations

import ast
import json
import shutil
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .manifest import (
    PluginManifest,
    PluginManifestRecord,
    PluginManifestRegistry,
    PluginSandboxProfile,
    PluginState,
)


class ManagedPluginState(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    REVOKED = "revoked"
    FAILED = "failed"
    UNINSTALLED = "uninstalled"


class ManagedPluginRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    package_path: Path
    state: ManagedPluginState = ManagedPluginState.DISABLED
    reason: str = ""
    previous_versions: list[str] = Field(default_factory=list)


class PluginConformanceResult(BaseModel):
    plugin_id: str
    version: str
    valid: bool
    errors: list[str] = Field(default_factory=list)


class PluginLifecycleManager:
    """Manage local manifest packages without importing third-party code."""

    def __init__(
        self,
        package_root: Path,
        revoked_ids: set[str] | None = None,
    ) -> None:
        self._root = package_root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._state_path = self._root / ".plugin-state.json"
        self._revoked_ids = set(revoked_ids or set())
        self._records = self._load_state()

    def records(self) -> list[ManagedPluginRecord]:
        return list(self._records.values())

    def install(self, source_package: Path) -> ManagedPluginRecord:
        manifest_record = self._verify_source(source_package)
        manifest = self._verified_manifest(manifest_record)
        destination = self._root / manifest.id / manifest.version
        if destination.exists():
            raise ValueError(f"plugin version already installed: {manifest.id}@{manifest.version}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_package, destination)
        copied = self._verify_source(destination)
        self._verified_manifest(copied)
        previous = self._records.get(manifest.id)
        versions = list(previous.previous_versions) if previous else []
        if previous is not None and previous.version not in versions:
            versions.append(previous.version)
        record = ManagedPluginRecord(
            plugin_id=manifest.id,
            version=manifest.version,
            package_path=destination,
            state=ManagedPluginState.DISABLED,
            reason="installed; explicit enablement is required",
            previous_versions=versions,
        )
        self._records[manifest.id] = record
        self._save_state()
        return record

    def enable(self, plugin_id: str) -> ManagedPluginRecord:
        record = self._require(plugin_id)
        if plugin_id in self._revoked_ids:
            record.state = ManagedPluginState.REVOKED
            record.reason = "plugin id is revoked by local policy"
            self._save_state()
            return record
        conformance = self.conformance(plugin_id)
        if not conformance.valid:
            record.state = ManagedPluginState.FAILED
            record.reason = "; ".join(conformance.errors)
            self._save_state()
            return record
        record.state = ManagedPluginState.ENABLED
        record.reason = "enabled after static conformance checks"
        self._save_state()
        return record

    def disable(self, plugin_id: str) -> ManagedPluginRecord:
        record = self._require(plugin_id)
        if record.state == ManagedPluginState.REVOKED:
            return record
        record.state = ManagedPluginState.DISABLED
        record.reason = "disabled by local policy"
        self._save_state()
        return record

    def revoke(self, plugin_id: str) -> ManagedPluginRecord:
        record = self._require(plugin_id)
        self._revoked_ids.add(plugin_id)
        record.state = ManagedPluginState.REVOKED
        record.reason = "plugin id is revoked by local policy"
        self._save_state()
        return record

    def rollback(self, plugin_id: str, version: str) -> ManagedPluginRecord:
        record = self._require(plugin_id).model_copy(deep=True)
        package_path = self._root / plugin_id / version
        self._verified_manifest(self._verify_source(package_path))
        if record.version != version and record.version not in record.previous_versions:
            record.previous_versions.append(record.version)
        record.version = version
        record.package_path = package_path
        record.state = ManagedPluginState.DISABLED
        record.reason = "rolled back; explicit enablement is required"
        self._save_state()
        return record

    def uninstall(self, plugin_id: str) -> ManagedPluginRecord:
        record = self._require(plugin_id)
        package_path = record.package_path.resolve()
        if self._root not in package_path.parents:
            raise ValueError("plugin package path is outside the managed package root")
        if package_path.exists():
            shutil.rmtree(package_path)
        record.state = ManagedPluginState.UNINSTALLED
        record.reason = "uninstalled; evidence and audit data are retained separately"
        self._save_state()
        return record

    def conformance(self, plugin_id: str) -> PluginConformanceResult:
        record = self._require(plugin_id)
        errors: list[str] = []
        try:
            manifest = self._verified_manifest(self._verify_source(record.package_path))
        except ValueError as exc:
            return PluginConformanceResult(
                plugin_id=record.plugin_id,
                version=record.version,
                valid=False,
                errors=[str(exc)],
            )
        if manifest.sandbox != PluginSandboxProfile.CONTAINER:
            errors.append("untrusted plugins must request the container sandbox profile")
        try:
            source = manifest.entrypoint_path(record.package_path).read_text(
                encoding="utf-8"
            )
            module = ast.parse(source)
            _, _, function_name = manifest.entrypoint.partition(":")
            if not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == function_name
                for node in module.body
            ):
                errors.append("entrypoint callable is not defined in the entrypoint module")
        except (OSError, SyntaxError, ValueError) as exc:
            errors.append(f"entrypoint static inspection failed: {exc}")
        return PluginConformanceResult(
            plugin_id=record.plugin_id,
            version=record.version,
            valid=not errors,
            errors=errors,
        )

    def _verify_source(self, package_path: Path) -> PluginManifestRecord:
        manifest_path = package_path / "plugin.json"
        registry = PluginManifestRegistry(package_path.parent, self._revoked_ids)
        return registry._read_record(manifest_path)

    @staticmethod
    def _verified_manifest(record: PluginManifestRecord) -> PluginManifest:
        if record.state != PluginState.VERIFIED or record.manifest is None:
            raise ValueError(record.reason or "plugin manifest is not verified")
        return record.manifest

    def _require(self, plugin_id: str) -> ManagedPluginRecord:
        record = self._records.get(plugin_id)
        if record is None:
            raise ValueError(f"managed plugin not found: {plugin_id}")
        return record

    def _load_state(self) -> dict[str, ManagedPluginRecord]:
        if not self._state_path.exists():
            return {}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            return {
                item["plugin_id"]: ManagedPluginRecord.model_validate(item)
                for item in payload
            }
        except (OSError, ValueError, TypeError):
            return {}

    def _save_state(self) -> None:
        payload = [record.model_dump(mode="json") for record in self.records()]
        self._state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
