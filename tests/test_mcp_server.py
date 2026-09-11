"""Tests for the De-code MCP/HTTP server core (transport-independent)."""

import asyncio
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from decode.app.config import Config
from decode.hostcontrol import PermissionMode
from decode.mcp import DecodeMCPServer, MCPServerConfig

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


class MCPServerCoreTest(unittest.TestCase):
    def setUp(self):
        self._prev_home = os.environ.get("DECODE_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DECODE_HOME"] = self._tmp.name
        Config.reload()
        Config.ensure_dirs()
        # A working directory used as the filesystem scope for file tools.
        self.work = Path(self._tmp.name) / "work"
        self.work.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self._prev_home is None:
            os.environ.pop("DECODE_HOME", None)
        else:
            os.environ["DECODE_HOME"] = self._prev_home
        Config.reload()
        self._tmp.cleanup()

    def _server(self, mode=PermissionMode.ASK, enabled=None):
        config = MCPServerConfig(
            mode=mode,
            read_roots=[str(self.work)],
            write_roots=[str(self.work)],
            enabled_tools=enabled,
        )
        return DecodeMCPServer(config)

    def test_list_tools_exposes_governed_capabilities(self):
        tools = self._server().list_tools()
        names = {t["name"] for t in tools}
        for expected in ("shell_command", "file_read", "file_write", "list_tools"):
            self.assertIn(expected, names)
        sample = next(t for t in tools if t["name"] == "file_read")
        self.assertTrue(sample["governed"])
        self.assertEqual(sample["input_schema"]["type"], "object")

    def test_enabled_tools_filter(self):
        server = self._server(enabled=["file_read"])
        names = {t["name"] for t in server.list_tools()}
        self.assertEqual(names, {"file_read"})
        result = asyncio.run(server.call_tool("shell_command", {"command": "echo hi"}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")

    def test_unknown_tool(self):
        result = asyncio.run(self._server().call_tool("does_not_exist"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertIn("unknown", result["error"])

    def test_read_tool_allowed_in_ask_mode(self):
        target = self.work / "note.txt"
        target.write_text("hello", encoding="utf-8")
        result = asyncio.run(
            self._server().call_tool("file_read", {"path": str(target)})
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "success")

    def test_plan_mode_denies_everything(self):
        target = self.work / "note.txt"
        target.write_text("hello", encoding="utf-8")
        result = asyncio.run(
            self._server(mode=PermissionMode.PLAN).call_tool(
                "file_read", {"path": str(target)}
            )
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "denied")

    def test_write_requires_approval_in_ask_mode(self):
        target = self.work / "out.txt"
        result = asyncio.run(
            self._server().call_tool(
                "file_write", {"path": str(target), "content": "data"}
            )
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_category"], "approval_required")

    def test_write_allowed_in_auto_mode(self):
        target = self.work / "out.txt"
        result = asyncio.run(
            self._server(mode=PermissionMode.AUTO).call_tool(
                "file_write", {"path": str(target), "content": "data"}
            )
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(target.read_text(encoding="utf-8"), "data")

    def test_health(self):
        health = self._server().health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["service"], "decode-mcp")
        self.assertGreater(health["tools"], 0)


class MCPServerConfigTest(unittest.TestCase):
    def test_config_roundtrip(self):
        config = MCPServerConfig(
            host="127.0.0.1",
            port=9000,
            mode=PermissionMode.AUTO,
            read_roots=["/a"],
            write_roots=["/a"],
            enabled_tools=["file_read"],
        )
        restored = MCPServerConfig.from_dict(config.to_dict())
        self.assertEqual(restored.port, 9000)
        self.assertEqual(restored.mode, PermissionMode.AUTO)
        self.assertEqual(restored.enabled_tools, ["file_read"])
        self.assertTrue(restored.is_local)
        self.assertEqual(restored.url, "http://127.0.0.1:9000")


@unittest.skipUnless(_HAS_FASTAPI, "requires the optional decode[server] extra")
class MCPServerHTTPTest(unittest.TestCase):
    """Exercise the FastAPI transport so request-body parsing can't regress."""

    def setUp(self):
        self._prev_home = os.environ.get("DECODE_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DECODE_HOME"] = self._tmp.name
        Config.reload()
        Config.ensure_dirs()
        self.work = Path(self._tmp.name) / "work"
        self.work.mkdir(parents=True, exist_ok=True)

        from fastapi.testclient import TestClient

        from decode.mcp.transport import build_fastapi_app

        server = DecodeMCPServer(
            MCPServerConfig(
                mode=PermissionMode.AUTO,
                read_roots=[str(self.work)],
                write_roots=[str(self.work)],
            )
        )
        self.client = TestClient(build_fastapi_app(server))

    def tearDown(self):
        if self._prev_home is None:
            os.environ.pop("DECODE_HOME", None)
        else:
            os.environ["DECODE_HOME"] = self._prev_home
        Config.reload()
        self._tmp.cleanup()

    def test_health_and_tools(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        self.assertGreater(len(self.client.get("/tools").json()["tools"]), 0)

    def test_call_tool_receives_arguments(self):
        target = self.work / "note.txt"
        target.write_text("hi there", encoding="utf-8")
        resp = self.client.post(
            "/tools/file_read", json={"arguments": {"path": str(target)}}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["status"], "success")

    def test_bare_arguments_body_accepted(self):
        target = self.work / "note.txt"
        target.write_text("hi there", encoding="utf-8")
        # No "arguments" wrapper — the bare object is treated as the arguments.
        resp = self.client.post("/tools/file_read", json={"path": str(target)})
        self.assertTrue(resp.json()["ok"], resp.json())


if __name__ == "__main__":
    unittest.main()
