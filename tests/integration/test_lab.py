"""Opt-in integration tests against the controlled lab (docker/lab).

These are skipped by the normal unit suite. They require real tools and the lab
network, so they run only inside the lab runner with DECODE_LAB=1. See
docker/lab/docker-compose.yml.
"""

import asyncio
import os
import shutil
import unittest

LAB_ENABLED = os.getenv("DECODE_LAB") == "1"
LAB_TARGET = os.getenv("LAB_TARGET", "target-web")


@unittest.skipUnless(LAB_ENABLED, "set DECODE_LAB=1 inside the lab runner to enable")
class TestLabCapabilityCoverage(unittest.TestCase):
    def _run(self, capability: str, params: dict, tool: str):
        if shutil.which(tool) is None:
            self.skipTest(f"{tool} not installed in this environment")
        from decode.capabilities.registry import CapabilityRegistry
        from decode.discovery.engine import DiscoveryEngine

        report = DiscoveryEngine().discover_sync()
        registry = CapabilityRegistry(report)
        resolution = registry.resolve(capability, params)
        return asyncio.run(registry.execute(capability, params, tool=resolution.tool.name, resolution=resolution))

    def test_port_scan_finds_web_port(self):
        result = self._run("port_scan", {"target": LAB_TARGET, "ports": "80"}, "nmap")
        self.assertTrue(result.success)
        ports = [p.get("port") for p in result.normalized.get("ports", [])]
        self.assertIn(80, ports)

    def test_http_fingerprint_identifies_server(self):
        result = self._run("http_fingerprint", {"target": f"http://{LAB_TARGET}"}, "httpx")
        self.assertTrue(result.success or result.partial)


if __name__ == "__main__":
    unittest.main()
