import asyncio
import shutil
import time
from collections.abc import Sequence

from .base import (
    Command,
    EnvironmentCapabilities,
    ExecutionContext,
    ExecutionProvider,
    ExecutionResult,
    FilesystemMode,
    ProviderPathMapping,
    command_display,
)


class WSLExecutor(ExecutionProvider):
    """Runs commands inside a WSL distribution on Windows via `wsl.exe`.

    Lets Decode reach a Linux toolchain (nmap, ffuf, ...) from a Windows host
    without Docker. Selects a specific distro when given, else the default.
    """

    def __init__(
        self,
        distro: str | None = None,
        path_mappings: Sequence[ProviderPathMapping] = (),
    ) -> None:
        self._distro = distro
        self._path_mappings = tuple(path_mappings)

    @property
    def name(self) -> str:
        return f"wsl/{self._distro}" if self._distro else "wsl"

    @property
    def platform(self) -> str:
        return "linux"

    @property
    def command_timeout_seconds(self) -> int:
        return 120

    @property
    def filesystem_mode(self) -> FilesystemMode:
        return FilesystemMode.MAPPED

    @property
    def path_mappings(self) -> tuple[ProviderPathMapping, ...]:
        return self._path_mappings

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(
            command_execution=True,
            tool_discovery=True,
            cwd=True,
            environment=True,
            path_mapping=bool(self.path_mappings),
            scoped_filesystem=bool(self.path_mappings),
            stateful_sessions=True,
        )

    def _wsl_argv(
        self,
        command: Command,
        context: ExecutionContext | None = None,
    ) -> list[str]:
        execution_context = context or ExecutionContext()
        argv = ["wsl.exe"]
        if self._distro:
            argv += ["-d", self._distro]
        if execution_context.cwd:
            argv += ["--cd", execution_context.cwd]
        environment = [
            f"{name}={value}" for name, value in execution_context.environment.items()
        ]
        if isinstance(command, str):
            provider_command = ["/bin/sh", "-c", command]
        else:
            provider_command = [str(part) for part in command]
        if environment:
            provider_command = ["/usr/bin/env", *environment, *provider_command]
        argv += ["--", *provider_command]
        return argv

    async def execute(
        self,
        command: Command,
        timeout: int = 120,
        env: dict[str, str] | None = None,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        display = command_display(command)
        try:
            execution_context = self.prepare_context(context, env=env)
        except ValueError as exc:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=str(exc),
                exit_code=-1,
                error="invalid_execution_context",
            )
        if not shutil.which("wsl.exe"):
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr="wsl.exe not found on PATH",
                exit_code=-1,
                error="WSL not available",
            )
        start = time.time()
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._wsl_argv(command, execution_context),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=proc.returncode == 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                exit_code=proc.returncode if proc.returncode is not None else 0,
                duration=time.time() - start,
            )
        except TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=f"Command timed out after {timeout}s",
                exit_code=-1,
                duration=time.time() - start,
                timed_out=True,
            )
        except Exception as e:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=str(e),
                exit_code=-1,
                duration=time.time() - start,
                error=str(e),
            )

    async def check_health(self) -> bool:
        if not shutil.which("wsl.exe"):
            return False
        result = await self.execute("echo ok", timeout=15)
        return result.success
