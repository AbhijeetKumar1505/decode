import importlib
import pkgutil
from typing import Dict, Any, List, Optional
from .plugins.base import Plugin, RiskLevel as PluginRiskLevel
from .skills.registry import SkillRegistry
from .skills.base import Skill, RiskLevel as SkillRiskLevel


class PluginManager:
    def __init__(self, plugins_dir: str = "decode.plugins"):
        self.plugins_package = plugins_dir
        self.plugins: Dict[str, Plugin] = {}
        self._skill_registry = SkillRegistry()
        self._load_plugins()
        self._load_skills()

    def _load_plugins(self):
        """Dynamically load all old-style plugins from the plugins directory."""
        package = importlib.import_module(self.plugins_package)
        for _, name, is_pkg in pkgutil.iter_modules(package.__path__):
            if name == "base":
                continue

            module = importlib.import_module(f"{self.plugins_package}.{name}")
            for item_name in dir(module):
                item = getattr(module, item_name)
                if (
                    isinstance(item, type)
                    and issubclass(item, Plugin)
                    and item is not Plugin
                ):
                    plugin_instance = item()
                    self.plugins[plugin_instance.name] = plugin_instance

    def _load_skills(self):
        """Also discover new-style skills."""
        for skill in self._skill_registry.get_all():
            risk = PluginRiskLevel.READ
            if skill.spec.risk_level == SkillRiskLevel.WRITE:
                risk = PluginRiskLevel.WRITE
            elif skill.spec.risk_level == SkillRiskLevel.DESTRUCTIVE:
                risk = PluginRiskLevel.DESTRUCTIVE
            self.plugins[skill.spec.name] = _SkillAdapter(skill, risk)

    def get_plugin_list(self) -> List[Dict[str, Any]]:
        """Return a list of all registered plugins and their metadata."""
        return [p.to_dict() for p in self.plugins.values()]

    def get_plugin(self, name: str) -> Optional[Plugin]:
        return self.plugins.get(name)

    def execute_plugin(self, name: str, params: Dict[str, Any]) -> Any:
        if not self.get_plugin(name):
            raise ValueError(f"Plugin {name} not found")
        raise RuntimeError(
            "Direct plugin execution is disabled; resolve a registered capability "
            "or skill through ExecutionCoordinator"
        )

    def list_plugins(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "description": p.description,
                "risk_level": p.risk_level.value
                if hasattr(p.risk_level, "value")
                else str(p.risk_level),
                "schema": p.schema,
            }
            for p in self.plugins.values()
        ]


class _SkillAdapter(Plugin):
    """Adapts new-style Skill to old-style Plugin interface."""

    def __init__(self, skill: Skill, risk: PluginRiskLevel):
        super().__init__()
        self._skill = skill
        self.name = skill.spec.name
        self.description = skill.spec.description
        self.risk_level = risk
        self.schema = {
            "required": [k for k, v in skill.spec.input_schema.items() if v.required],
            "properties": {
                k: {"type": v.type, "description": v.description}
                for k, v in skill.spec.input_schema.items()
            },
        }

    def execute(self, **kwargs) -> Any:
        raise RuntimeError(
            "Direct skill-adapter execution is disabled; use ExecutionCoordinator"
        )
