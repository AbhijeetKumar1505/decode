import os
from pathlib import Path

from dotenv import load_dotenv


def load_config() -> None:
    """Finds and loads the .env file with explicit path checking."""
    cwd_env = Path.cwd() / ".env"
    pkg_env = Path(__file__).parent.parent / ".env"

    if cwd_env.exists():
        load_dotenv(cwd_env, override=True)
    elif pkg_env.exists():
        load_dotenv(pkg_env, override=True)
    else:
        load_dotenv(override=True)


load_config()


class Config:
    PROVIDER = os.getenv("DECODE_PROVIDER", "openrouter")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    MODEL = os.getenv("DECODE_MODEL", "z-ai/glm-5.2:free")
    EXECUTOR = os.getenv("DECODE_EXECUTOR", "local")
    MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", 20))
    MEMORY_PATH = Path(os.getenv("MEMORY_PATH", "./data/models/"))
    SANDBOX_IMAGE = "kalilinux/kali-rolling:latest"
    LOGS_PATH = Path(os.getenv("LOGS_PATH", "./logs/"))
    AUDIT_PATH = Path(os.getenv("AUDIT_PATH", "./audit/"))
    FEEDBACK_PATH = Path(os.getenv("FEEDBACK_PATH", "./feedback/"))
    EVIDENCE_PATH = Path(os.getenv("EVIDENCE_PATH", "./evidence/"))
    TOOL_REGISTRY_PATH = Path(os.getenv("TOOL_REGISTRY_PATH", "./data/tool_registry.json"))
    PROFILES_PATH = Path(os.getenv("PROFILES_PATH", "./profiles/"))
    MONGODB_URI = os.getenv("MONGODB_URI")
    MONGODB_DB = os.getenv("MONGODB_DB", "decode")
    SEARCH_ENGINE = os.getenv("DECODE_SEARCH_ENGINE", "duckduckgo")

    @classmethod
    def reload(cls) -> None:
        """Reload variables from .env."""
        load_config()
        cls.PROVIDER = os.getenv("DECODE_PROVIDER", "openrouter")
        cls.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
        cls.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        cls.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        cls.MODEL = os.getenv("DECODE_MODEL", "z-ai/glm-5.2:free")
        cls.EXECUTOR = os.getenv("DECODE_EXECUTOR", "local")
        cls.MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", 20))
        cls.MEMORY_PATH = Path(os.getenv("MEMORY_PATH", "./data/models/"))
        cls.LOGS_PATH = Path(os.getenv("LOGS_PATH", "./logs/"))
        cls.AUDIT_PATH = Path(os.getenv("AUDIT_PATH", "./audit/"))
        cls.FEEDBACK_PATH = Path(os.getenv("FEEDBACK_PATH", "./feedback/"))
        cls.EVIDENCE_PATH = Path(os.getenv("EVIDENCE_PATH", "./evidence/"))
        cls.TOOL_REGISTRY_PATH = Path(os.getenv("TOOL_REGISTRY_PATH", "./data/tool_registry.json"))
        cls.PROFILES_PATH = Path(os.getenv("PROFILES_PATH", "./profiles/"))
        cls.MONGODB_URI = os.getenv("MONGODB_URI")
        cls.MONGODB_DB = os.getenv("MONGODB_DB", "decode")
        cls.SEARCH_ENGINE = os.getenv("DECODE_SEARCH_ENGINE", "duckduckgo")

    @classmethod
    def provider_key_name(cls, provider: str | None = None) -> str:
        names = {
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        selected = (provider or cls.PROVIDER).lower()
        if selected not in names:
            raise ValueError(f"Unknown provider: {selected}. Available: {list(names)}")
        return names[selected]

    @classmethod
    def has_provider_credentials(cls, provider: str | None = None) -> bool:
        key_name = cls.provider_key_name(provider)
        return bool(getattr(cls, key_name))

    @classmethod
    def validate(cls, provider: str | None = None) -> None:
        key_name = cls.provider_key_name(provider)
        if not getattr(cls, key_name):
            raise ValueError(f"{key_name} required in .env")
        cls.MEMORY_PATH.mkdir(parents=True, exist_ok=True)

    @classmethod
    def ensure_dirs(cls) -> None:
        for path in [
            cls.MEMORY_PATH,
            cls.LOGS_PATH,
            cls.AUDIT_PATH,
            cls.FEEDBACK_PATH,
            cls.EVIDENCE_PATH,
            cls.PROFILES_PATH,
        ]:
            path.mkdir(parents=True, exist_ok=True)
