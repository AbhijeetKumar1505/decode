import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.extensions import ExtensionManager, Scope, ScopedStore, deep_merge
from decode.extensions.paths import project_root, user_root


class TestPaths(unittest.TestCase):
    def test_user_root_honors_env(self):
        with mock.patch.dict("os.environ", {"DECODE_HOME": "/tmp/decode-home"}):
            self.assertEqual(user_root(), Path("/tmp/decode-home"))

    def test_project_root_honors_env(self):
        with mock.patch.dict("os.environ", {"DECODE_PROJECT_HOME": "/tmp/proj/.decode"}):
            self.assertEqual(project_root(), Path("/tmp/proj/.decode"))

    def test_project_root_finds_nearest_dot_decode(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / ".decode").mkdir()
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            with mock.patch.dict("os.environ", {}, clear=False):
                import os
                os.environ.pop("DECODE_PROJECT_HOME", None)
                self.assertEqual(project_root(nested), root / ".decode")


class TestDeepMerge(unittest.TestCase):
    def test_overlay_wins_and_nested_merges(self):
        base = {"a": 1, "n": {"x": 1, "y": 2}}
        overlay = {"a": 2, "n": {"y": 3, "z": 4}}
        self.assertEqual(deep_merge(base, overlay), {"a": 2, "n": {"x": 1, "y": 3, "z": 4}})


class TestScopedStore(unittest.TestCase):
    def _env(self, user, project):
        return mock.patch.dict("os.environ", {
            "DECODE_HOME": str(user),
            "DECODE_PROJECT_HOME": str(project),
            "DECODE_SYSTEM_HOME": str(user / "nonexistent-system"),
        })

    def test_write_read_and_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            user, project = base / "user", base / "project"
            store = ScopedStore("mcp.json")
            with self._env(user, project):
                store.write_scope(Scope.USER, {"mongodb": {"enabled": True}, "github": {"enabled": True}})
                store.write_scope(Scope.PROJECT, {"github": {"enabled": False}})
                merged = store.read_merged()
                # project overrides user for the same key
                self.assertFalse(merged["github"]["enabled"])
                self.assertTrue(merged["mongodb"]["enabled"])

    def test_update_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            user, project = base / "user", base / "project"
            store = ScopedStore("mcp.json")
            with self._env(user, project):
                store.update_scope(Scope.USER, "mongodb", {"enabled": True})
                self.assertIn("mongodb", store.read_scope(Scope.USER))
                self.assertTrue(store.delete_key(Scope.USER, "mongodb"))
                self.assertNotIn("mongodb", store.read_scope(Scope.USER))
                self.assertFalse(store.delete_key(Scope.USER, "missing"))


class TestExtensionManager(unittest.TestCase):
    def test_settings_merge(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            user, project = base / "user", base / "project"
            with mock.patch.dict("os.environ", {
                "DECODE_HOME": str(user), "DECODE_PROJECT_HOME": str(project),
                "DECODE_SYSTEM_HOME": str(base / "nope"),
            }):
                mgr = ExtensionManager()
                mgr.config.write_scope(Scope.USER, {"theme": "dark", "verbose": False})
                mgr.config.write_scope(Scope.PROJECT, {"verbose": True})
                settings = mgr.settings()
                self.assertEqual(settings["theme"], "dark")
                self.assertTrue(settings["verbose"])


if __name__ == "__main__":
    unittest.main()
