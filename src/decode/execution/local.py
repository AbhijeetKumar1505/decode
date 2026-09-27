import asyncio
import os
import sys
import time

from .base import (
    Command,
    EnvironmentCapabilities,
    ExecutionContext,
    ExecutionProvider,
    ExecutionResult,
    FilesystemMode,
    command_display,
)


class LocalExecutor(ExecutionProvider):
    """Runs commands directly on the host via an asyncio subprocess shell."""

    DEFAULT_TIMEOUT = 120

    @property
    def name(self) -> str:
        return "local"

    @property
    def platform(self) -> str:
        return sys.platform

    @property
    def filesystem_mode(self) -> FilesystemMode:
        return FilesystemMode.SHARED

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(
            command_execution=True,
            tool_discovery=True,
            cwd=True,
            environment=True,
            path_mapping=True,
            scoped_filesystem=True,
            stateful_sessions=True,
        )

    async def execute(
        self,
        command: Command,
        timeout: int = DEFAULT_TIMEOUT,
        env: dict[str, str] | None = None,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        start = time.time()
        proc = None
        display = command_display(command)
        try:
            execution_context = self.prepare_context(context, env=env)
            process_env = None
            if execution_context.environment:
                process_env = {**os.environ, **execution_context.environment}
            if isinstance(command, str):
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=execution_context.cwd or None,
                    env=process_env,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *(str(part) for part in command),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=execution_context.cwd or None,
                    env=process_env,
                )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            duration = time.time() - start
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=proc.returncode == 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                exit_code=proc.returncode if proc.returncode is not None else 0,
                duration=duration,
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
        except FileNotFoundError as e:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=str(e),
                exit_code=-1,
                duration=time.time() - start,
                error=f"Command not found: {e}",
            )
        except ValueError as e:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=str(e),
                exit_code=-1,
                duration=time.time() - start,
                error="invalid_execution_context",
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
        result = await self.execute("echo ok", timeout=10)
        return result.success
