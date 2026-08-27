import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from decode.plugins.manifest import PluginManifestRegistry, PluginState


class TestPluginManifestRegistry(unittest.TestCase):
    def _write_manifest_plugin(
        self,
        root: Path,
        plugin_id: str = "example.safe-plugin",
        source: str = "raise RuntimeError('entrypoint must not be imported')\n",
        source_digest: str | None = None,
    ) -> None:
        plugin_root = root / plugin_id
        plugin_root.mkdir()
        (plugin_root / "entry.py").write_text(source, encoding="utf-8")
        digest = source_digest or hashlib.sha256(source.encode("utf-8")).hexdigest()
        manifest = {
            "schema_version": "1.0.0",
            "id": plugin_id,
            "version": "1.0.0",
            "entrypoint": "entry:register",
            "decode": ">=1.0,<2.0",
            "source_digest": f"sha256:{digest}",
            "capabilities": [{"id": "example.inspect", "risk": "READ"}],
            "permissions": {"network": "none"},
            "dependencies": {"python": [], "tools": []},
            "platforms": ["linux", "windows"],
            "sandbox": "restricted_subprocess",
        }
        (plugin_root / "plugin.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def test_discovers_and_verifies_manifest_without_importing_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest_plugin(root)

            records = PluginManifestRegistry(root).discover()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].state, PluginState.VERIFIED)
        self.assertTrue(records[0].source_verified)
        self.assertEqual(records[0].manifest.id, "example.safe-plugin")

    def test_digest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest_plugin(root, source_digest="0" * 64)

            records = PluginManifestRegistry(root).discover()

        self.assertEqual(records[0].state, PluginState.FAILED)
        self.assertIn("digest", records[0].reason)

    def test_revoked_plugin_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest_plugin(root)

            records = PluginManifestRegistry(
                root,
                revoked_ids={"example.safe-plugin"},
            ).discover()

        self.assertEqual(records[0].state, PluginState.REVOKED)
        self.assertFalse(records[0].source_verified)

    def test_disable_changes_verified_manifest_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest_plugin(root)
            registry = PluginManifestRegistry(root)
            registry.discover()

            disabled = registry.disable("example.safe-plugin")

        self.assertEqual(disabled.state, PluginState.DISABLED)
        self.assertEqual(disabled.reason, "disabled by local policy")


if __name__ == "__main__":
    unittest.main()
