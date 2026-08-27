import hashlib
import unittest
from pathlib import Path

from decode.plugins.manifest import PluginManifest
from decode.plugins.sandbox import PluginContainerProfile


class TestPluginContainerProfile(unittest.TestCase):
    def _manifest(self, network: str = "none") -> PluginManifest:
        source = "def register():\n    return {}\n"
        return PluginManifest.model_validate(
            {
                "schema_version": "1.0.0",
                "id": "example.sandbox",
                "version": "1.0.0",
                "entrypoint": "entry:register",
                "decode": ">=1.0,<2.0",
                "source_digest": "sha256:" + hashlib.sha256(source.encode()).hexdigest(),
                "capabilities": [{"id": "example.inspect", "risk": "READ"}],
                "permissions": {"network": network},
                "dependencies": {"python": [], "tools": []},
                "platforms": ["linux"],
                "sandbox": "container",
            }
        )

    def test_builds_non_networked_read_only_command(self) -> None:
        command = PluginContainerProfile().build_command(
            self._manifest(), Path("/tmp/plugin")
        )

        self.assertIn("--network=none", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--security-opt=no-new-privileges", command)

    def test_networked_manifest_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "networked"):
            PluginContainerProfile().build_command(
                self._manifest("scoped_targets"), Path("/tmp/plugin")
            )


if __name__ == "__main__":
    unittest.main()
