import asyncio
import time

from .base import Command, ExecutionProvider, ExecutionResult, command_display


class DockerExecutor(ExecutionProvider):
    """Runs commands inside a disposable Docker container.

    Networking is opt-in (default 'bridge', not host). Real exit codes are
    captured via container.wait(); logs are read before the container is
    removed to avoid the remove/log race in the v1 implementation.
    """

    def __init__(
        self,
        image: str = "kalilinux/kali-rolling:latest",
        mem_limit: str = "512m",
        network: str = "bridge",
    ):
        self._image = image
        self._mem_limit = mem_limit
        self._network = network
        self._client = None

    @property
    def name(self) -> str:
        return f"docker/{self._image}"

    def _get_client(self):
        if self._client is None:
            import docker

            self._client = docker.from_env()
            self._client.ping()
        return self._client

    def _run_sync(
        self,
        command: Command,
        timeout: int,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        start = time.time()
        display = command_display(command)
        client = self._get_client()
        container = client.containers.run(
            self._image,
            command=["/bin/sh", "-c", command]
            if isinstance(command, str)
            else [str(part) for part in command],
            detach=True,
            remove=False,
            mem_limit=self._mem_limit,
            environment=env or {},
            network_mode=self._network,
        )
        try:
            try:
                status = container.wait(timeout=timeout)
                exit_code = status.get("StatusCode", -1)
                timed_out = False
            except Exception:
                # wait() timed out; stop the container and mark accordingly
                try:
                    container.stop(timeout=1)
                except Exception:
                    pass
                exit_code = -1
                timed_out = True
            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=(exit_code == 0 and not timed_out),
                stdout=stdout,
                stderr=stderr if not timed_out else f"Timed out after {timeout}s",
                exit_code=exit_code,
                duration=time.time() - start,
                timed_out=timed_out,
            )
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass

    async def execute(
        self, command: Command, timeout: int = 60, env: dict[str, str] | None = None
    ) -> ExecutionResult:
        display = command_display(command)
        try:
            return await asyncio.to_thread(self._run_sync, command, timeout, env)
        except ImportError:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr="Docker SDK not installed",
                exit_code=-1,
                error="Docker SDK not installed",
            )
        except Exception as e:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=str(e),
                exit_code=-1,
                error=str(e),
            )

    async def check_health(self) -> bool:
        def _ping() -> bool:
            try:
                self._get_client().ping()
                return True
            except Exception:
                return False

        try:
            return await asyncio.to_thread(_ping)
        except Exception:
            return False
