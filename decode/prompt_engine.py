import yaml
from jinja2 import Template
from pathlib import Path
from typing import Dict, Any


class PromptEngine:
    def __init__(self, prompts_dir: str = "./prompts"):
        self.prompts_dir = Path(prompts_dir)
        self.system_dir = self.prompts_dir / "system"
        self.domains_dir = self.prompts_dir / "domains"
        self.templates_dir = self.prompts_dir / "templates"

    def load_domain(self, domain_name: str) -> Dict[str, Any]:
        domain_file = self.domains_dir / f"{domain_name}.yaml"
        if not domain_file.exists():
            return {}
        with open(domain_file, "r") as f:
            return yaml.safe_load(f)

    def load_system_config(
        self, config_name: str = "universal_agent"
    ) -> Dict[str, Any]:
        config_file = self.system_dir / f"{config_name}.yaml"
        with open(config_file, "r") as f:
            return yaml.safe_load(f)

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        # Check if it's a jinja2 template in templates/
        template_file = self.templates_dir / f"{template_name}.j2"
        if template_file.exists():
            with open(template_file, "r") as f:
                template = Template(f.read())
                return template.render(**context)

        # Fallback to system prompt in yaml
        config = self.load_system_config(template_name)
        template_str = config.get("system_prompt", "")
        template = Template(template_str)
        return template.render(**context)
