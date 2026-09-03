import unittest

from decode.prompting import PromptComposer, compose_system_prompt
from decode.schema import TaskMode

TOOLS = [
    {"name": "list_tools", "description": "List installed tools"},
    {"name": "shell_command", "description": "Run a policy-checked command"},
    {"name": "git_diff", "description": "Show the working-tree diff"},
]


class TestPromptComposer(unittest.TestCase):
    def test_all_modes_compose_and_carry_contract_and_capabilities(self):
        for mode in (TaskMode.CODING, TaskMode.SECURITY, TaskMode.HYBRID):
            prompt = compose_system_prompt(mode, TOOLS)
            # response contract
            self.assertIn('"tool"', prompt)
            self.assertIn('"message"', prompt)
            # capabilities injected
            self.assertIn("git_diff", prompt)
            self.assertIn("shell_command", prompt)
            # policy + task-state note injected
            self.assertIn("scope", prompt.lower())
            self.assertIn("task state", prompt.lower())

    def test_mode_fragments_differ(self):
        coding = compose_system_prompt(TaskMode.CODING, TOOLS)
        security = compose_system_prompt(TaskMode.SECURITY, TOOLS)
        self.assertIn("SOFTWARE ENGINEERING", coding)
        self.assertIn("AUTHORIZED SECURITY", security)
        self.assertNotEqual(coding, security)

    def test_project_rules_appended_when_present(self):
        prompt = compose_system_prompt(
            TaskMode.HYBRID, TOOLS, project_rules="Never touch main directly."
        )
        self.assertIn("Project rules:", prompt)
        self.assertIn("Never touch main directly.", prompt)
        # absent by default
        self.assertNotIn(
            "Project rules:", compose_system_prompt(TaskMode.HYBRID, TOOLS)
        )

    def test_custom_policy_context_overrides_default(self):
        prompt = compose_system_prompt(
            TaskMode.HYBRID, TOOLS, policy_context="CUSTOM POLICY XYZ"
        )
        self.assertIn("CUSTOM POLICY XYZ", prompt)

    def test_composer_object_holds_mode(self):
        composer = PromptComposer(mode=TaskMode.SECURITY, project_rules="rule-1")
        prompt = composer.compose(TOOLS)
        self.assertIn("AUTHORIZED SECURITY", prompt)
        self.assertIn("rule-1", prompt)


if __name__ == "__main__":
    unittest.main()
