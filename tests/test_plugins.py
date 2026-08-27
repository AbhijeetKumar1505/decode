import unittest

from decode.plugins.recon import SubdomainEnumerator
from decode.plugins.web import DirBruteScanner
from decode.tools import PluginManager


class TestPlugins(unittest.TestCase):
    def setUp(self):
        self.pm = PluginManager()

    def test_plugin_registration(self):
        self.assertIn("dir_brute", self.pm.plugins)
        self.assertIn("subdomain_enum", self.pm.plugins)

        dir_brute = self.pm.get_plugin("dir_brute")
        sub_enum = self.pm.get_plugin("subdomain_enum")
        self.assertEqual(dir_brute.name, "dir_brute")
        self.assertEqual(sub_enum.name, "subdomain_enum")

    def test_manager_direct_execution_is_quarantined(self):
        with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
            self.pm.execute_plugin("dir_brute", {"target": "192.0.2.10"})

    def test_skill_adapter_direct_execution_is_quarantined(self):
        adapter = self.pm.get_plugin("nmap_scan")
        with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
            adapter.execute(target="192.0.2.10")

    def test_old_style_plugin_classes_are_quarantined(self):
        cases = [
            (DirBruteScanner(), {"url": "https://example.invalid"}),
            (SubdomainEnumerator(), {"domain": "example.invalid"}),
        ]
        for plugin, params in cases:
            with self.subTest(plugin=plugin.name):
                with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
                    plugin.execute(**params)


if __name__ == "__main__":
    unittest.main()
