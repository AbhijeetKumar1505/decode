import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from decode.audit import AuditLayer
from decode.execution import MCPExecutor, create_executor
from decode.governance import GovernanceGate, ScopePolicy
from decode.runtime import ExecutionCoordinator, ExecutionRequest
from decode.skills.base import RiskLevel


class _FakeMCPClient:
    def __init__(self, healthy=True, raises=False):
        self.healthy = healthy
        self.raises = raises
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.raises:
            raise RuntimeError("tool exploded")
        return {"tool": name, "args": arguments, "result": "ok"}

    async def check(self):
        return self.healthy


def _run_provider(executor, command):
    with tempfile.TemporaryDirectory() as directory:
        audit = AuditLayer(Path(directory) / "audit")
        coordinator = ExecutionCoordinator(
            GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
            audit=audit,
        )
        request = ExecutionRequest(
            action="mcp_test",
            risk=RiskLevel.READ,
            command=command,
            executor=executor.name,
        )

        async def operation():
            return await executor.execute(command)

        return asyncio.run(coordinator.execute(request, operation)).value


class TestMCPExecutor(unittest.TestCase):
    def test_encode_roundtrip(self):
        cmd = MCPExecutor.encode("port_scan", {"target": "10.0.0.5"})
        payload = json.loads(cmd)
        self.assertEqual(payload["tool"], "port_scan")
        self.assertEqual(payload["arguments"]["target"], "10.0.0.5")

    def test_structured_call_succeeds(self):
        client = _FakeMCPClient()
        ex = MCPExecutor(server="lab", client=client)
        r = _run_provider(ex, MCPExecutor.encode("port_scan", {"target": "10.0.0.5"}))
        self.assertTrue(r.success)
        self.assertEqual(r.metadata["tool"], "port_scan")
        self.assertIn("ok", r.stdout)
        self.assertEqual(client.calls[0][0], "port_scan")
        self.assertEqual(ex.name, "mcp/lab")

    def test_invalid_command_is_rejected(self):
        ex = MCPExecutor(client=_FakeMCPClient())
        r = _run_provider(ex, "not json")
        self.assertFalse(r.success)
        self.assertEqual(r.error, "invalid_mcp_command")

    def test_argument_vector_is_rejected_in_favor_of_structured_payload(self):
        ex = MCPExecutor(client=_FakeMCPClient())
        r = _run_provider(ex, ["port_scan", "192.0.2.10"])

        self.assertFalse(r.success)
        self.assertEqual(r.error, "invalid_mcp_command")

    def test_tool_error_is_captured(self):
        ex = MCPExecutor(client=_FakeMCPClient(raises=True))
        r = _run_provider(ex, MCPExecutor.encode("boom"))
        self.assertFalse(r.success)
        self.assertIn("exploded", r.stderr)

    def test_health_reflects_client(self):
        self.assertTrue(
            asyncio.run(MCPExecutor(client=_FakeMCPClient(healthy=True)).check_health())
        )
        self.assertFalse(
            asyncio.run(
                MCPExecutor(client=_FakeMCPClient(healthy=False)).check_health()
            )
        )

    def test_factory_builds_mcp_with_client(self):
        client = _FakeMCPClient()
        ex = create_executor("mcp", server="lab", client=client)
        self.assertIsInstance(ex, MCPExecutor)
        r = _run_provider(ex, MCPExecutor.encode("t"))
        self.assertTrue(r.success)


if __name__ == "__main__":
    unittest.main()
