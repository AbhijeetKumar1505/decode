from typing import Dict, Type
from .base import ExecutionProvider
from .local import LocalExecutor
from .docker import DockerExecutor
from .wsl import WSLExecutor
from .ssh import SSHExecutor
from .mcp import MCPExecutor


# Providers constructible with no required arguments — usable as defaults and
# discoverable by the `providers` CLI. SSHExecutor is excluded (needs a host).
_ZERO_ARG_PROVIDERS: Dict[str, Type[ExecutionProvider]] = {
    "local": LocalExecutor,
    "docker": DockerExecutor,
    "wsl": WSLExecutor,
    "mcp": MCPExecutor,
}

_ALL_PROVIDERS: Dict[str, Type[ExecutionProvider]] = {
    **_ZERO_ARG_PROVIDERS,
    "ssh": SSHExecutor,
}


def available_provider_names() -> list:
    """Provider names that can be instantiated without extra configuration."""
    return list(_ZERO_ARG_PROVIDERS.keys())


def create_executor(name: str = "local", **kwargs) -> ExecutionProvider:
    cls = _ALL_PROVIDERS.get(name.lower())
    if not cls:
        raise ValueError(
            f"Unknown execution provider: {name}. Available: {list(_ALL_PROVIDERS.keys())}"
        )
    return cls(**kwargs)
