import asyncio
import shlex
import shutil
import time
from typing import Optional, Dict, List
from .base import Command, ExecutionProvider, ExecutionResult, command_display


class SSHExecutor(ExecutionProvider):
    """Runs commands on a remote host via the system `ssh` client.

    Dependency-light (no paramiko): shells out to the OpenSSH binary. Assumes
    key-based auth is already configured for the target — Decode never handles
    credentials directly. BatchMode disables interactive prompts so a missing
    key fails fast instead of hanging.
    """

    def __init__(
        self,
        host: str,
        user: Optional[str] = None,
        port: int = 22,
        identity_file: Optional[str] = None,
    ):
        self._host = host
        self._user = user
        self._port = port
        self._identity_file = identity_file

    @property
    def name(self) -> str:
        target = f"{self._user}@{self._host}" if self._user else self._host
        return f"ssh/{target}:{self._port}"

    def _ssh_argv(self, command: Command) -> List[str]:
        argv = [
            "ssh",
            "-p", str(self._port),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
        ]
        if self._identity_file:
            argv += ["-i", self._identity_file]
        target = f"{self._user}@{self._host}" if self._user else self._host
        remote_command = command if isinstance(command, str) else shlex.join(command)
        argv += [target, remote_command]
        return argv

    async def execute(
        self, command: Command, timeout: int = 120, env: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        display = command_display(command)
        if not shutil.which("ssh"):
            return ExecutionResult(
                command=display, provider=self.name, success=False,
                stderr="ssh client not found on PATH", exit_code=-1,
                error="SSH client not available",
            )
        start = time.time()
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._ssh_argv(command),
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
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            return ExecutionResult(
                command=display, provider=self.name, success=False,
                stderr=f"Command timed out after {timeout}s", exit_code=-1,
                duration=time.time() - start, timed_out=True,
            )
        except Exception as e:
            return ExecutionResult(
                command=display, provider=self.name, success=False,
                stderr=str(e), exit_code=-1,
                duration=time.time() - start, error=str(e),
            )

    async def check_health(self) -> bool:
        if not shutil.which("ssh"):
            return False
        result = await self.execute("echo ok", timeout=15)
        return result.success
