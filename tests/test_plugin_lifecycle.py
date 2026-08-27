import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from decode.plugins.lifecycle import (
    ManagedPluginState,
    PluginLifecycleManager,
)


class TestPluginLifecycle(unittest.TestCase):
    def _package(self, root: Path, version: str = "1.0.0") -> Path:
        package = root / f"source-{version}" / "plugin"
        package.parent.mkdir()
        package.mkdir()
        source = "def register():\n    return {}\n"
        (package / "entry.py").write_text(source, encoding="utf-8")
        manifest = {
            "schema_version": "1.0.0",
            "id": "example.lifecycle",
            "version": version,
            "entrypoint": "entry:register",
            "decode": ">=1.0,<2.0",
            "source_digest": "sha256:" + hashlib.sha256(source.encode()).hexdigest(),
            "capabilities": [{"id": "example.inspect", "risk": "READ"}],
            "permissions": {"network": "none"},
            "dependencies": {"python": [], "tools": []},
            "platforms": ["linux"],
            "sandbox": "container",
        }
        (package / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        return package

    def test_install_enable_disable_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = PluginLifecycleManager(root / "managed")
            installed = manager.install(self._package(root))
            enabled = manager.enable(installed.plugin_id)
            disabled = manager.disable(installed.plugin_id)
            restored = PluginLifecycleManager(root / "managed").records()[0]

        self.assertEqual(installed.state, ManagedPluginState.DISABLED)
        self.assertEqual(enabled.state, ManagedPluginState.DISABLED)
        self.assertEqual(disabled.state, ManagedPluginState.DISABLED)
        self.assertEqual(restored.state, ManagedPluginState.DISABLED)

    def test_upgrade_and_rollback_keep_previous_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = PluginLifecycleManager(root / "managed")
            manager.install(self._package(root, "1.0.0"))
            upgraded = manager.install(self._package(root, "1.1.0"))
            rolled_back = manager.rollback(upgraded.plugin_id, "1.0.0")

        self.assertEqual(upgraded.version, "1.1.0")
        self.assertIn("1.0.0", upgraded.previous_versions)
        self.assertEqual(rolled_back.version, "1.0.0")

    def test_revocation_prevents_enablement_and_uninstall_removes_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = PluginLifecycleManager(root / "managed")
            installed = manager.install(self._package(root))
            revoked = manager.revoke(installed.plugin_id)
            removed = manager.uninstall(installed.plugin_id)

        self.assertEqual(revoked.state, ManagedPluginState.UNINSTALLED)
        self.assertEqual(removed.state, ManagedPluginState.UNINSTALLED)
        self.assertFalse(removed.package_path.exists())


if __name__ == "__main__":
    unittest.main()
