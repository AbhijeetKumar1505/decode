from .base import ExecutionProvider
from .docker import DockerExecutor
from .local import LocalExecutor
from .mcp import MCPExecutor
from .ssh import SSHExecutor
from .wsl import WSLExecutor

# Providers constructible with no required arguments — usable as defaults and
# discoverable by the `providers` CLI. SSHExecutor is excluded (needs a host).
_ZERO_ARG_PROVIDERS: dict[str, type[ExecutionProvider]] = {
    "local": LocalExecutor,
    "docker": DockerExecutor,
    "wsl": WSLExecutor,
    "mcp": MCPExecutor,
}

_ALL_PROVIDERS: dict[str, type[ExecutionProvider]] = {
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
