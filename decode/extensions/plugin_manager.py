"""Plugin packages — declarative capability bundles (extension layer D).

A De-code plugin is a *package*, not in-process code: a ``manifest.json`` plus
markdown skills, MCP server configs, and command/agent docs. Nothing in a plugin
is imported or executed in-process — its skills run as governed ``shell_command``
playbooks and its MCP servers run as isolated external processes. This is what
lets plugins be "special additions" without the arbitrary-code-execution risk of
the removed in-tree plugin loader.

Install verifies the manifest, copies the package into the plugin store, and
registers its components (MCP servers into the shared config; skill directories
exposed for playbook discovery). Remove reverses it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .mcp_manager import MCPManager, MCPServerSpec
from .paths import Scope, ensure_scope, user_root
from .store import ScopedStore

_DOC_SUFFIXES = {".md"}


class PluginManifest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = "0.0.0"
    description: str = ""
    skills: List[str] = Field(default_factory=list)
    mcp: List[str] = Field(default_factory=list)
    commands: List[str] = Field(default_factory=list)
    agents: List[str] = Field(default_factory=list)


class PluginRecord(BaseModel):
    name: str
    version: str = "0.0.0"
    description: str = ""
    path: str = ""
    enabled: bool = True
    mcp_servers: List[str] = Field(default_factory=list)
    skill_dirs: List[str] = Field(default_factory=list)


def _safe_member(base: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``base``, rejecting traversal outside the package."""
    base_r = base.resolve()
    member = (base_r / rel).resolve()
    if member != base_r and base_r not in member.parents:
        raise ValueError(f"plugin path escapes the package: {rel}")
    return member


def verify_manifest(source: Path) -> PluginManifest:
    """Parse and validate a plugin manifest, failing closed on anything unsafe."""
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("plugin is missing manifest.json")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"invalid manifest.json: {exc}") from exc
    manifest = PluginManifest(**data)
    for group in (manifest.skills, manifest.commands, manifest.agents):
        for rel in group:
            member = _safe_member(source, rel)
            if not member.exists():
                raise ValueError(f"declared plugin path does not exist: {rel}")
            if member.is_file() and member.suffix.lower() not in _DOC_SUFFIXES:
                raise ValueError(f"skill/command/agent files must be markdown: {rel}")
    for rel in manifest.mcp:
        member = _safe_member(source, rel)
        if not member.is_file() or member.suffix.lower() != ".json":
            raise ValueError(f"mcp entry must be a .json file: {rel}")
    return manifest


class PluginManager:
    def __init__(
        self,
        default_scope: Scope = Scope.USER,
        store: Optional[ScopedStore] = None,
        mcp_manager: Optional[MCPManager] = None,
        store_dir: Optional[Path] = None,
    ) -> None:
        self._store = store or ScopedStore("plugins.json")
        self._default_scope = default_scope
        self._mcp = mcp_manager or MCPManager(default_scope=default_scope)
        self._store_dir = store_dir or (user_root() / "plugins")

    # ── lifecycle ───────────────────────────────────────────────────────
    def install(self, source: Path, scope: Optional[Scope] = None) -> PluginManifest:
        source = Path(source)
        manifest = verify_manifest(source)
        target_scope = scope or self._default_scope
        ensure_scope(target_scope)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        dest = self._store_dir / manifest.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)

        mcp_servers = self._register_mcp(manifest, dest, target_scope)
        skill_dirs = self._skill_dirs(manifest, dest)
        record = PluginRecord(
            name=manifest.name, version=manifest.version, description=manifest.description,
            path=str(dest), enabled=True, mcp_servers=mcp_servers,
            skill_dirs=[str(d) for d in skill_dirs],
        )
        self._store.update_scope(target_scope, manifest.name, record.model_dump())
        return manifest

    def remove(self, name: str, scope: Optional[Scope] = None) -> bool:
        target_scope = scope or self._default_scope
        data = self._store.read_scope(target_scope)
        if name not in data:
            return False
        record = PluginRecord(**data[name])
        for server in record.mcp_servers:
            self._mcp.remove(server, scope=target_scope)
        if record.path:
            shutil.rmtree(Path(record.path), ignore_errors=True)
        return self._store.delete_key(target_scope, name)

    def list_plugins(self) -> Dict[str, PluginRecord]:
        return {
            name: PluginRecord(**{**data, "name": name})
            for name, data in self._store.read_merged().items()
            if isinstance(data, dict)
        }

    def get(self, name: str) -> Optional[PluginRecord]:
        return self.list_plugins().get(name)

    def set_enabled(self, name: str, enabled: bool, scope: Optional[Scope] = None) -> bool:
        target_scope = scope or self._default_scope
        data = self._store.read_scope(target_scope)
        if name not in data:
            merged = self.get(name)
            if merged is None:
                return False
            data[name] = merged.model_dump()
        data[name]["enabled"] = enabled
        self._store.write_scope(target_scope, data)
        # mirror enable/disable onto the plugin's MCP servers
        for server in PluginRecord(**data[name]).mcp_servers:
            self._mcp.set_enabled(server, enabled, scope=target_scope)
        return True

    # ── component contribution ──────────────────────────────────────────
    def enabled_skill_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        for record in self.list_plugins().values():
            if record.enabled:
                dirs.extend(Path(d) for d in record.skill_dirs)
        return dirs

    def _register_mcp(self, manifest: PluginManifest, dest: Path, scope: Scope) -> List[str]:
        names: List[str] = []
        for rel in manifest.mcp:
            servers = json.loads((dest / rel).read_text(encoding="utf-8"))
            for server_name, spec_data in (servers or {}).items():
                spec = MCPServerSpec(**{**spec_data, "name": server_name})
                self._mcp.add(spec, scope=scope)
                names.append(server_name)
        return names

    @staticmethod
    def _skill_dirs(manifest: PluginManifest, dest: Path) -> List[Path]:
        dirs: List[Path] = []
        for rel in manifest.skills:
            member = (dest / rel).resolve()
            dirs.append(member if member.is_dir() else member.parent)
        return dirs
