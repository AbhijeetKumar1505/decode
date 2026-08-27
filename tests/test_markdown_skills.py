import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from decode.audit import AuditLayer
from decode.governance import GovernanceGate, ScopePolicy
from decode.runtime import ExecutionCoordinator, ExecutionRequest
from decode.skills.base import RiskLevel, SkillCategory
from decode.skills.markdown_skill import (
    MarkdownSkill,
    discover_markdown_skills,
    parse_markdown_skill,
)
from decode.skills.registry import SkillRegistry


_SAMPLE = """---
name: sample_playbook
description: A synthetic playbook for tests.
category: web_scanning
risk: READ
tags:
  - web
  - recon
inputs:
  target:
    type: string
    description: target url
    required: true
target_required: true
---

# Sample

Step one. Step two.
"""


class TestMarkdownSkillParsing(unittest.TestCase):
    def test_frontmatter_maps_to_spec(self):
        skill = parse_markdown_skill(_SAMPLE, fallback_name="fallback")
        self.assertIsInstance(skill, MarkdownSkill)
        self.assertEqual(skill.spec.name, "sample_playbook")
        self.assertEqual(skill.spec.category, SkillCategory.WEB_SCANNING)
        self.assertEqual(skill.spec.risk_level, RiskLevel.READ)
        self.assertIn("target", skill.spec.input_schema)
        # markers are appended to declared tags
        self.assertIn("playbook", skill.spec.tags)
        self.assertIn("markdown", skill.spec.tags)
        self.assertTrue(skill.spec.requires_scoped_target())

    def test_body_becomes_instructions(self):
        skill = parse_markdown_skill(_SAMPLE, fallback_name="fallback")
        self.assertIn("Step one", skill._instructions)
        self.assertNotIn("---", skill._instructions)

    def test_no_frontmatter_uses_fallback_name_and_defaults(self):
        skill = parse_markdown_skill("# Just a body\n", fallback_name="bare")
        self.assertEqual(skill.spec.name, "bare")
        self.assertEqual(skill.spec.risk_level, RiskLevel.READ)
        self.assertEqual(skill.spec.category, SkillCategory.AGENT_CORE)
        self.assertIn("Just a body", skill._instructions)

    def test_unknown_category_and_risk_fall_back(self):
        text = "---\nname: x\ncategory: not_a_category\nrisk: BOGUS\n---\nbody"
        skill = parse_markdown_skill(text, fallback_name="x")
        self.assertEqual(skill.spec.category, SkillCategory.AGENT_CORE)
        self.assertEqual(skill.spec.risk_level, RiskLevel.READ)


class TestMarkdownSkillDiscovery(unittest.TestCase):
    def test_packaged_playbook_is_discovered(self):
        names = [s.spec.name for s in discover_markdown_skills()]
        self.assertIn("web_recon_playbook", names)

    def test_registry_includes_markdown_skills(self):
        names = [s.spec.name for s in SkillRegistry().get_all()]
        self.assertIn("web_recon_playbook", names)

    def test_env_directory_is_scanned_and_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "extra.md").write_text(
                "---\nname: env_playbook\ndescription: from env\n---\nbody",
                encoding="utf-8",
            )
            prev = os.environ.get("DECODE_PLAYBOOKS_DIR")
            os.environ["DECODE_PLAYBOOKS_DIR"] = directory
            try:
                names = [s.spec.name for s in discover_markdown_skills()]
            finally:
                if prev is None:
                    os.environ.pop("DECODE_PLAYBOOKS_DIR", None)
                else:
                    os.environ["DECODE_PLAYBOOKS_DIR"] = prev
        self.assertIn("env_playbook", names)

    def test_malformed_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            # invalid YAML in the frontmatter block
            (Path(directory) / "broken.md").write_text(
                "---\nname: [unclosed\n---\nbody", encoding="utf-8"
            )
            (Path(directory) / "ok.md").write_text(
                "---\nname: ok_playbook\n---\nbody", encoding="utf-8"
            )
            prev = os.environ.get("DECODE_PLAYBOOKS_DIR")
            os.environ["DECODE_PLAYBOOKS_DIR"] = directory
            try:
                names = [s.spec.name for s in discover_markdown_skills()]
            finally:
                if prev is None:
                    os.environ.pop("DECODE_PLAYBOOKS_DIR", None)
                else:
                    os.environ["DECODE_PLAYBOOKS_DIR"] = prev
        self.assertIn("ok_playbook", names)
        self.assertNotIn("broken", names)


class TestMarkdownSkillExecution(unittest.TestCase):
    def test_execute_returns_guidance_through_coordinator(self):
        skill = parse_markdown_skill(_SAMPLE, fallback_name="fallback")
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLayer(Path(directory) / "audit")
            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                audit=audit,
            )
            request = ExecutionRequest(
                action=skill.spec.name,
                target="https://example.test",
                target_required=skill.spec.requires_scoped_target(),
                risk=skill.spec.risk_level,
                params={"target": "https://example.test"},
                executor="local",
            )

            async def operation():
                return await skill.execute(target="https://example.test")

            result = asyncio.run(coordinator.execute(request, operation))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.value["playbook"], "sample_playbook")
        self.assertIn("Step one", result.value["guidance"])

    def test_direct_execution_is_quarantined(self):
        skill = parse_markdown_skill(_SAMPLE, fallback_name="fallback")
        with self.assertRaisesRegex(RuntimeError, "ExecutionCoordinator"):
            asyncio.run(skill.execute(target="https://example.test"))


if __name__ == "__main__":
    unittest.main()
