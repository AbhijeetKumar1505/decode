import asyncio
import shutil
import time

from .base import Command, ExecutionProvider, ExecutionResult, command_display


class WSLExecutor(ExecutionProvider):
    """Runs commands inside a WSL distribution on Windows via `wsl.exe`.

    Lets Decode reach a Linux toolchain (nmap, ffuf, ...) from a Windows host
    without Docker. Selects a specific distro when given, else the default.
    """

    def __init__(self, distro: str | None = None):
        self._distro = distro

    @property
    def name(self) -> str:
        return f"wsl/{self._distro}" if self._distro else "wsl"

    def _wsl_argv(self, command: Command) -> list[str]:
        argv = ["wsl.exe"]
        if self._distro:
            argv += ["-d", self._distro]
        if isinstance(command, str):
            argv += ["--", "/bin/sh", "-c", command]
        else:
            argv += ["--", *(str(part) for part in command)]
        return argv

    async def execute(
        self, command: Command, timeout: int = 120, env: dict[str, str] | None = None
    ) -> ExecutionResult:
        display = command_display(command)
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
                *self._wsl_argv(command),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
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
