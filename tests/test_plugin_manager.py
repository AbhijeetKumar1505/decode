import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.extensions.mcp_manager import MCPManager
from decode.extensions.plugin_manager import PluginManager, verify_manifest


def _make_plugin(base: Path, name: str = "web-security") -> Path:
    pkg = base / name
    (pkg / "skills").mkdir(parents=True)
    (pkg / "mcp").mkdir(parents=True)
    (pkg / "skills" / "recon.md").write_text(
        "---\nname: web_recon_plus\ndescription: recon\nrisk: READ\n---\nStep 1.\n",
        encoding="utf-8",
    )
    (pkg / "mcp" / "servers.json").write_text(
        json.dumps(
            {
                "db": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "x"],
                    "risk": "read",
                }
            }
        ),
        encoding="utf-8",
    )
    (pkg / "manifest.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "1.0.0",
                "description": "web sec toolkit",
                "skills": ["skills"],
                "mcp": ["mcp/servers.json"],
            }
        ),
        encoding="utf-8",
    )
    return pkg


class TestVerifyManifest(unittest.TestCase):
    def test_valid(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = _make_plugin(Path(d))
            manifest = verify_manifest(pkg)
            self.assertEqual(manifest.name, "web-security")

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            verify_manifest(Path(d))

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = _make_plugin(Path(d))
            (pkg / "manifest.json").write_text(
                json.dumps({"name": "x", "skills": ["../escape"]}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                verify_manifest(pkg)

    def test_non_json_mcp_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = _make_plugin(Path(d))
            (pkg / "manifest.json").write_text(
                json.dumps({"name": "x", "mcp": ["skills/recon.md"]}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                verify_manifest(pkg)


class TestPluginManager(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._src = base / "src"
        self._src.mkdir()
        self._env = mock.patch.dict(
            "os.environ",
            {
                "DECODE_HOME": str(base / "home"),
                "DECODE_PROJECT_HOME": str(base / "project"),
                "DECODE_SYSTEM_HOME": str(base / "system"),
            },
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_install_registers_components(self):
        pkg = _make_plugin(self._src)
        mcp = MCPManager()
        pm = PluginManager(mcp_manager=mcp)
        manifest = pm.install(pkg)
        self.assertEqual(manifest.name, "web-security")
        # plugin recorded and enabled
        record = pm.get("web-security")
        self.assertTrue(record.enabled)
        # its MCP server was registered into the shared config
        self.assertIn("db", mcp.list_servers())
        # its skill directory is exposed for playbook discovery
        self.assertTrue(any("skills" in str(d) for d in pm.enabled_skill_dirs()))
        # the package was copied into the store
        self.assertTrue((Path(record.path) / "manifest.json").is_file())

    def test_disable_hides_skill_dirs_and_disables_mcp(self):
        pm = PluginManager(mcp_manager=MCPManager())
        pm.install(_make_plugin(self._src))
        pm.set_enabled("web-security", False)
        self.assertEqual(pm.enabled_skill_dirs(), [])

    def test_remove_reverses_install(self):
        mcp = MCPManager()
        pm = PluginManager(mcp_manager=mcp)
        pm.install(_make_plugin(self._src))
        path = Path(pm.get("web-security").path)
        self.assertTrue(pm.remove("web-security"))
        self.assertIsNone(pm.get("web-security"))
        self.assertNotIn("db", mcp.list_servers())
        self.assertFalse(path.exists())
        self.assertFalse(pm.remove("web-security"))  # idempotent


if __name__ == "__main__":
    unittest.main()
