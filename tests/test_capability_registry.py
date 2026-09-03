import unittest

from decode.capabilities.registry import build_registry
from decode.extensions.mcp_manager import MCPToolDescriptor
from decode.schema import TaskMode

HOST = [
    {"name": "file_read", "description": "read", "risk": "read"},
    {"name": "shell_command", "description": "run", "risk": "write"},
    {"name": "session_exec", "description": "session", "risk": "write"},
]
SKILLS = [
    {
        "name": "web_recon",
        "description": "recon",
        "risk": "read",
        "category": "web_scanning",
    },
    {
        "name": "tdd",
        "description": "test-driven development",
        "risk": "read",
        "category": "agent_core",
    },
]
MCP = [
    MCPToolDescriptor(
        server="db", name="db.find", tool="find", description="find", risk="read"
    )
]


def _names(descriptors):
    return {d["name"] for d in descriptors}


class TestCapabilityRegistry(unittest.TestCase):
    def test_source_tagging(self):
        reg = build_registry(HOST, SKILLS, MCP)
        self.assertEqual(reg.get("file_read").source, "native")
        self.assertEqual(reg.get("shell_command").source, "system")
        self.assertEqual(reg.get("session_exec").source, "system")
        self.assertEqual(reg.get("git_diff").source, "native")
        self.assertEqual(reg.get("git_diff").type, "coding")
        self.assertEqual(reg.get("web_recon").source, "skill")
        db = reg.get("db.find")
        self.assertEqual((db.source, db.server, db.tool), ("mcp", "db", "find"))
        self.assertEqual(db.executor, "mcp/db")

    def test_resolve_hybrid_has_all_sources(self):
        names = _names(build_registry(HOST, SKILLS, MCP).resolve(TaskMode.HYBRID))
        self.assertTrue({"file_read", "git_diff", "web_recon", "db.find"} <= names)

    def test_resolve_coding_excludes_security_keeps_engineering_and_mcp(self):
        names = _names(build_registry(HOST, SKILLS, MCP).resolve(TaskMode.CODING))
        self.assertIn("git_diff", names)
        self.assertIn("db.find", names)  # mcp always available
        self.assertIn("tdd", names)  # engineering (agent_core) playbooks available
        self.assertNotIn("web_recon", names)  # security playbooks excluded

    def test_engineering_playbook_carries_category(self):
        reg = build_registry(HOST, SKILLS, MCP)
        self.assertEqual(reg.get("tdd").category, "agent_core")
        self.assertEqual(reg.get("web_recon").category, "web_scanning")

    def test_resolve_security_excludes_coding_keeps_mcp(self):
        names = _names(build_registry(HOST, SKILLS, MCP).resolve(TaskMode.SECURITY))
        self.assertIn("web_recon", names)
        self.assertIn("db.find", names)
        self.assertNotIn("git_diff", names)

    def test_by_source(self):
        reg = build_registry(HOST, SKILLS, MCP)
        self.assertEqual({c.name for c in reg.by_source("mcp")}, {"db.find"})


if __name__ == "__main__":
    unittest.main()
