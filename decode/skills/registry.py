import importlib
import pkgutil
from typing import Dict, Any, List, Optional
from .base import Skill, SkillCategory


class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._load_skills()

    def _load_skills(self):
        packages = ["decode.skills", "decode.plugins"]
        for pkg_name in packages:
            try:
                package = importlib.import_module(pkg_name)
                path = getattr(package, "__path__", None)
                if path is None:
                    continue
                self._load_from_path(pkg_name, path)
            except ImportError:
                continue
        self._load_markdown_skills()

    def _load_markdown_skills(self):
        try:
            from .markdown_skill import discover_markdown_skills
        except ImportError:
            return
        for skill in discover_markdown_skills():
            self._skills[skill.spec.name] = skill

    def _load_from_path(self, pkg_name: str, path):
        for _, name, is_pkg in pkgutil.iter_modules(path):
            if name in ("base", "__init__"):
                continue
            module_name = f"{pkg_name}.{name}"
            if is_pkg:
                try:
                    sub_pkg = importlib.import_module(module_name)
                    sub_path = getattr(sub_pkg, "__path__", None)
                    if sub_path:
                        self._load_from_path(module_name, sub_path)
                except ImportError:
                    continue
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            for item_name in dir(module):
                item = getattr(module, item_name)
                if (
                    isinstance(item, type)
                    and issubclass(item, Skill)
                    and item is not Skill
                ):
                    try:
                        instance = item()
                    except TypeError:
                        # Skills requiring constructor arguments (e.g. MarkdownSkill)
                        # are not auto-instantiable; they register themselves.
                        continue
                    self._skills[instance.spec.name] = instance

    def get_all(self) -> List[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def find_by_category(self, category: SkillCategory) -> List[Skill]:
        return [s for s in self._skills.values() if s.spec.category == category]

    def find_by_tags(self, tags: List[str]) -> List[Skill]:
        return [s for s in self._skills.values() if any(t in s.spec.tags for t in tags)]

    def search(self, query: str) -> List[Skill]:
        query = query.lower()
        return [
            s
            for s in self._skills.values()
            if query in s.spec.name.lower()
            or query in s.spec.description.lower()
            or any(query in t.lower() for t in s.spec.tags)
        ]

    def execute(self, name: str, **params) -> Dict[str, Any]:
        if not self.get(name):
            raise ValueError(f"Skill '{name}' not found")
        raise RuntimeError(
            "Direct SkillRegistry execution is disabled; use ExecutionCoordinator"
        )

    def list_summary(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s.spec.name,
                "description": s.spec.description,
                "category": s.spec.category.value,
                "risk_level": s.spec.risk_level.value,
                "tags": s.spec.tags,
                "dependencies": [
                    dependency.model_dump() for dependency in s.spec.dependencies
                ],
                "required_privileges": s.spec.required_privileges,
            }
            for s in self._skills.values()
        ]
