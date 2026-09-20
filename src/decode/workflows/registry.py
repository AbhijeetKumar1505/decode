"""Discovery for declarative workflows embedded in markdown playbooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..skills.markdown_skill import playbook_directories, split_frontmatter
from .models import WorkflowSpec


def parse_workflow(text: str, *, fallback_name: str, source: str = "") -> WorkflowSpec | None:
    frontmatter, body = split_frontmatter(text)
    if not frontmatter.strip():
        return None
    meta = yaml.safe_load(frontmatter)
    if not isinstance(meta, dict) or not isinstance(meta.get("workflow"), dict):
        return None
    workflow: dict[str, Any] = dict(meta["workflow"])
    workflow.setdefault("name", str(meta.get("name") or fallback_name))
    workflow.setdefault("description", str(meta.get("description") or ""))
    workflow.setdefault("target_required", bool(meta.get("target_required", False)))
    workflow["guidance"] = body.strip()
    workflow["source"] = source
    return WorkflowSpec.model_validate(workflow)


def load_workflow(path: Path) -> WorkflowSpec | None:
    return parse_workflow(
        path.read_text(encoding="utf-8"),
        fallback_name=path.stem,
        source=str(path),
    )


class WorkflowRegistry:
    """A small interface over packaged and configured workflow manifests."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowSpec] = {}
        self._load()

    def _load(self) -> None:
        for directory in playbook_directories():
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.md")):
                try:
                    workflow = load_workflow(path)
                except (OSError, yaml.YAMLError, ValueError):
                    continue
                if workflow is not None:
                    self._workflows[workflow.name] = workflow

    def all(self) -> list[WorkflowSpec]:
        return sorted(self._workflows.values(), key=lambda item: item.name)

    def get(self, name: str) -> WorkflowSpec | None:
        return self._workflows.get(name)
