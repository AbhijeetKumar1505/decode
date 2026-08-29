import unittest

from decode.capabilities.resolver import resolve_tools
from decode.schema import TaskMode

HOST = [
    {"name": "file_read", "description": "read"},
    {"name": "shell_command", "description": "run"},
]
SKILLS = [{"name": "web_recon", "description": "web recon playbook"}]


def _names(tools):
    return {t["name"] for t in tools}


class TestCapabilityResolver(unittest.TestCase):
    def test_coding_mode_has_coding_not_skills(self):
        names = _names(resolve_tools(TaskMode.CODING, HOST, SKILLS))
        self.assertIn("file_read", names)      # host always present
        self.assertIn("git_diff", names)       # coding present
        self.assertNotIn("web_recon", names)   # security playbooks excluded

    def test_security_mode_has_skills_not_coding(self):
        names = _names(resolve_tools(TaskMode.SECURITY, HOST, SKILLS))
        self.assertIn("web_recon", names)
        self.assertIn("shell_command", names)
        self.assertNotIn("git_diff", names)

    def test_hybrid_has_everything(self):
        names = _names(resolve_tools(TaskMode.HYBRID, HOST, SKILLS))
        self.assertIn("git_commit", names)
        self.assertIn("web_recon", names)
        self.assertIn("file_read", names)

    def test_overrides_win(self):
        names = _names(resolve_tools(TaskMode.SECURITY, HOST, SKILLS, include_coding=True))
        self.assertIn("git_diff", names)

    def test_deduplicates_by_name(self):
        host = HOST + [{"name": "file_read", "description": "dup"}]
        tools = resolve_tools(TaskMode.HYBRID, host, SKILLS)
        self.assertEqual(len([t for t in tools if t["name"] == "file_read"]), 1)


if __name__ == "__main__":
    unittest.main()
