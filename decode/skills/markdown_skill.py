"""Markdown-authored skills (``SKILL.md``): playbooks the agent reads as guidance.

A markdown skill is a ``.md`` file with a YAML frontmatter block (name,
description, risk, category, tags, inputs) followed by a body of instructions.
Unlike the Python skills, a markdown skill executes *nothing itself*: invoking it
returns its instructions as an observation, and the agent then carries them out
through the governed ``shell_command`` capability (each command separately scoped,
risk-classified, and audited). This lets new capabilities be authored as prose
guidance instead of a hardcoded Python wrapper, without weakening governance.

Discovery scans the package ``playbooks/`` directory plus any directories named in
the ``DECODE_PLAYBOOKS_DIR`` environment variable (``os.pathsep``-separated).
Malformed files are skipped rather than breaking registry load.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .base import RiskLevel, Skill, SkillCategory, SkillIO, SkillSpec

_ENV_DIRS = "DECODE_PLAYBOOKS_DIR"
_PACKAGE_PLAYBOOKS = Path(__file__).parent / "playbooks"


def _package_dirs() -> List[Path]:
    dirs = [_PACKAGE_PLAYBOOKS]
    extra = os.environ.get(_ENV_DIRS, "")
    for part in extra.split(os.pathsep):
        part = part.strip()
        if part:
            dirs.append(Path(part).expanduser())
    return dirs


def _split_frontmatter(text: str) -> Tuple[str, str]:
    """Return (frontmatter, body). No leading ``---`` means no frontmatter."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return "", text
    # Consume the leading fence, then split on the next line that is exactly '---'.
    after = stripped[3:].lstrip("\n")
    lines = after.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[:index]), "\n".join(lines[index + 1 :])
    return "", text  # unterminated fence: treat the whole file as body


def _category(value: Any) -> SkillCategory:
    if isinstance(value, str):
        try:
            return SkillCategory(value.strip().lower())
        except ValueError:
            pass
    return SkillCategory.AGENT_CORE


def _risk(value: Any) -> RiskLevel:
    if isinstance(value, str):
        try:
            return RiskLevel(value.strip().upper())
        except ValueError:
            pass
    # A playbook itself only returns guidance; the commands it triggers are gated
    # per-command, so retrieval defaults to READ.
    return RiskLevel.READ


def _input_schema(value: Any) -> Dict[str, SkillIO]:
    schema: Dict[str, SkillIO] = {}
    if isinstance(value, dict):
        for name, field in value.items():
            field = field or {}
            schema[str(name)] = SkillIO(
                type=str(field.get("type", "string")),
                description=str(field.get("description", "")),
                required=bool(field.get("required", True)),
            )
    return schema


def spec_from_meta(meta: Dict[str, Any], *, fallback_name: str) -> SkillSpec:
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    tags = [str(t) for t in tags]
    for marker in ("playbook", "markdown"):
        if marker not in tags:
            tags.append(marker)
    return SkillSpec(
        name=str(meta.get("name") or fallback_name),
        description=str(meta.get("description") or f"Markdown playbook '{fallback_name}'"),
        category=_category(meta.get("category")),
        risk_level=_risk(meta.get("risk")),
        input_schema=_input_schema(meta.get("inputs")),
        tags=tags,
        requires_approval=bool(meta.get("requires_approval", False)),
        target_required=meta.get("target_required"),
    )


def parse_markdown_skill(text: str, *, fallback_name: str) -> "MarkdownSkill":
    frontmatter, body = _split_frontmatter(text)
    meta = yaml.safe_load(frontmatter) if frontmatter.strip() else {}
    if not isinstance(meta, dict):
        meta = {}
    spec = spec_from_meta(meta, fallback_name=fallback_name)
    return MarkdownSkill(spec, body.strip())


def load_markdown_skill(path: Path) -> "MarkdownSkill":
    text = path.read_text(encoding="utf-8")
    return parse_markdown_skill(text, fallback_name=path.stem)


def discover_markdown_skills() -> List["MarkdownSkill"]:
    """Load every ``.md`` playbook from the package and configured directories.

    A file that fails to parse is skipped so one bad playbook never breaks skill
    registration. On a name collision the later directory wins (env dirs override
    the packaged defaults).
    """
    skills: Dict[str, MarkdownSkill] = {}
    for directory in _package_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            try:
                skill = load_markdown_skill(path)
            except (OSError, yaml.YAMLError, ValueError):
                continue
            skills[skill.spec.name] = skill
    return list(skills.values())


class MarkdownSkill(Skill):
    """A skill whose behavior is prose guidance, executed via ``shell_command``.

    Constructed with a parsed spec and instruction body, so the module-scanning
    registry (which instantiates skills with no arguments) skips it — markdown
    skills are registered explicitly by ``discover_markdown_skills``.
    """

    def __init__(self, spec: SkillSpec, instructions: str) -> None:
        self._spec = spec
        self._instructions = instructions
        super().__init__()

    def _build_spec(self) -> SkillSpec:
        return self._spec

    async def execute(self, **params: Any) -> Dict[str, Any]:
        return {
            "playbook": self._spec.name,
            "risk": self._spec.risk_level.value,
            "guidance": self._instructions,
            "note": (
                "Carry out these steps yourself via shell_command; each command is "
                "governed independently. If a referenced tool is not installed, "
                "report it — do not install anything."
            ),
        }
