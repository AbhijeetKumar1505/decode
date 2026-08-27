"""Conservative container command construction for untrusted plugin packages."""

from __future__ import annotations

from pathlib import Path

from .manifest import PluginManifest, PluginSandboxProfile


class PluginContainerProfile:
    """Build a non-networked, read-only Docker invocation for a plugin package."""

    def __init__(
        self,
        image: str = "python:3.11-alpine",
        memory_limit: str = "256m",
        cpu_limit: str = "0.5",
        pids_limit: int = 64,
    ) -> None:
        self._image = image
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._pids_limit = pids_limit

    def build_command(self, manifest: PluginManifest, package_path: Path) -> list[str]:
        if manifest.sandbox != PluginSandboxProfile.CONTAINER:
            raise ValueError("untrusted plugin execution requires the container profile")
        if manifest.permissions.network != "none":
            raise ValueError("networked plugin containers are not supported")
        package_root = package_path.resolve()
        entrypoint_module, _, entrypoint_callable = manifest.entrypoint.partition(":")
        return [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--pids-limit={self._pids_limit}",
            f"--memory={self._memory_limit}",
            f"--cpus={self._cpu_limit}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
            f"--mount=type=bind,src={package_root},dst=/plugin,readonly",
            "--workdir=/plugin",
            self._image,
            "python",
            "-I",
            "-S",
            "-c",
            (
                "import importlib; "
                f"getattr(importlib.import_module('{entrypoint_module}'), "
                f"'{entrypoint_callable}')()"
            ),
        ]
