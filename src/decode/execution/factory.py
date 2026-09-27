import json
import os

from pydantic import ValidationError

from .base import ExecutionProvider, FilesystemMode, ProviderPathMapping
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
    normalized = name.strip()
    provider_name, separator, qualifier = normalized.partition("/")
    if not separator and ":" in normalized:
        provider_name, _, qualifier = normalized.partition(":")
    provider_name = provider_name.lower()
    if provider_name == "wsl" and qualifier:
        kwargs.setdefault("distro", qualifier)
    elif qualifier:
        raise ValueError(
            f"Qualified execution provider is not supported: {name}. "
            "Only wsl/<distribution> may be qualified."
        )
    cls = _ALL_PROVIDERS.get(provider_name)
    if not cls:
        raise ValueError(
            f"Unknown execution provider: {name}. Available: {list(_ALL_PROVIDERS.keys())}"
        )
    return cls(**kwargs)


def create_configured_executor(name: str = "local", **kwargs) -> ExecutionProvider:
    """Apply exact-identity provider mappings from the user/project environment."""
    raw = os.getenv("DECODE_PROVIDER_MAPPINGS", "").strip()
    if not raw:
        return create_executor(name, **kwargs)
    try:
        configuration = json.loads(raw)
        if not isinstance(configuration, dict) or not configuration:
            raise ValueError("expected a non-empty provider object")
        provider = create_executor(name, **kwargs)
        if provider.filesystem_mode not in {
            FilesystemMode.MAPPED,
            FilesystemMode.REMOTE,
        }:
            if provider.name in configuration:
                raise ValueError("selected provider does not support path mappings")
            return provider
        for identity, entries in configuration.items():
            if (
                not isinstance(identity, str)
                or not identity
                or not isinstance(entries, list)
            ):
                raise ValueError("invalid provider mapping entry")
        entries = configuration.get(provider.name, [])
        mappings = tuple(ProviderPathMapping.model_validate(item) for item in entries)
        roots = [mapping.host_root for mapping in mappings]
        if len(roots) != len(set(roots)):
            raise ValueError("duplicate host roots in provider mapping")
        if "path_mappings" in kwargs:
            raise ValueError("path_mappings cannot be supplied twice")
        return create_executor(name, path_mappings=mappings, **kwargs)
    except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
        raise ValueError("Invalid DECODE_PROVIDER_MAPPINGS configuration") from exc
