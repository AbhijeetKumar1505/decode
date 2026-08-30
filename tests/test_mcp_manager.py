import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.extensions.mcp_manager import MCPManager, MCPServerSpec


class _FakeClient:
    def __init__(self, tools):
        self._tools = tools
        self.calls = []

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"ok": True}


def _factory(tools):
    return lambda spec: _FakeClient(tools)


class TestMCPManager(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._env = mock.patch.dict("os.environ", {
            "DECODE_HOME": str(base / "user"),
            "DECODE_PROJECT_HOME": str(base / "project"),
            "DECODE_SYSTEM_HOME": str(base / "system"),
        })
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _mgr(self, tools=None):
        return MCPManager(client_factory=_factory(tools or []))

    def test_add_list_get_remove(self):
        mgr = self._mgr()
        mgr.add(MCPServerSpec(name="mongodb", command="npx", args=["-y", "mongodb-mcp-server"], description="db"))
        servers = mgr.list_servers()
        self.assertIn("mongodb", servers)
        self.assertEqual(servers["mongodb"].command, "npx")
        self.assertEqual(mgr.get("mongodb").args, ["-y", "mongodb-mcp-server"])
        self.assertTrue(mgr.remove("mongodb"))
        self.assertNotIn("mongodb", mgr.list_servers())

    def test_add_rejects_bad_risk(self):
        with self.assertRaises(ValueError):
            self._mgr().add(MCPServerSpec(name="x", risk="nuclear"))

    def test_discover_namespaces_tools_and_carries_risk(self):
        tools = [
            {"name": "find", "description": "query documents", "inputSchema": {"type": "object"}},
            {"name": "aggregate", "description": "aggregation pipeline"},
        ]
        mgr = self._mgr(tools)
        mgr.add(MCPServerSpec(name="mongodb", command="npx", risk="read"))
        descriptors = asyncio.run(mgr.discover("mongodb"))
        self.assertEqual([d.name for d in descriptors], ["mongodb.find", "mongodb.aggregate"])
        self.assertEqual(descriptors[0].tool, "find")
        self.assertTrue(all(d.risk == "read" for d in descriptors))

    def test_available_tools_excludes_disabled(self):
        mgr = self._mgr([{"name": "find"}])
        mgr.add(MCPServerSpec(name="a", command="x"))
        mgr.add(MCPServerSpec(name="b", command="y"))
        mgr.set_enabled("b", False)
        names = {d.name for d in asyncio.run(mgr.available_tools())}
        self.assertIn("a.find", names)
        self.assertNotIn("b.find", names)

    def test_disabled_server_discovers_nothing(self):
        mgr = self._mgr([{"name": "find"}])
        mgr.add(MCPServerSpec(name="a", command="x"))
        mgr.set_enabled("a", False)
        self.assertEqual(asyncio.run(mgr.discover("a")), [])

    def test_executor_is_bound_to_server(self):
        mgr = self._mgr([{"name": "find"}])
        mgr.add(MCPServerSpec(name="mongodb", command="x"))
        asyncio.run(mgr.discover("mongodb"))  # starts the client
        executor = mgr.executor_for("mongodb")
        self.assertEqual(executor.name, "mcp/mongodb")


if __name__ == "__main__":
    unittest.main()
