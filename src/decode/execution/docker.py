import asyncio
import time
from collections.abc import Sequence

from requests.exceptions import ReadTimeout

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
        path_mappings: Sequence[ProviderPathMapping] = (),
    ) -> None:
        self._image = image
        self._mem_limit = mem_limit
        self._network = network
        self._path_mappings = tuple(path_mappings)
        self._client = None

    @property
    def name(self) -> str:
        return f"docker/{self._image}"

    @property
    def platform(self) -> str:
        return "linux"

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
        )

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
        context: ExecutionContext,
    ) -> ExecutionResult:
        start = time.time()
        display = command_display(command)
        client = self._get_client()
        from docker.errors import ImageNotFound

        volumes = {
            mapping.host_root: {
                "bind": mapping.provider_root,
                "mode": "rw" if mapping.writable else "ro",
            }
            for mapping in self.path_mappings
        }
        try:
            container = client.containers.create(
                self._image,
                command=["/bin/sh", "-c", command]
                if isinstance(command, str)
                else [str(part) for part in command],
                detach=True,
                mem_limit=self._mem_limit,
                environment=context.environment,
                network_mode=self._network,
                volumes=volumes or None,
                working_dir=context.cwd or None,
            )
        except ImageNotFound:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=f"Required Docker image is not cached: {self._image}",
                exit_code=-1,
                error="docker_image_missing",
            )
        try:
            container.start()
            wait_error = ""
            try:
                status = container.wait(timeout=timeout)
                exit_code = (
                    status.get("StatusCode") if isinstance(status, dict) else None
                )
                if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                    exit_code = -1
                    wait_error = "invalid_docker_wait_status"
                timed_out = False
            except (ReadTimeout, TimeoutError):
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
                success=(exit_code == 0 and not timed_out and not wait_error),
                stdout=stdout,
                stderr=stderr or (f"Timed out after {timeout}s" if timed_out else ""),
                exit_code=exit_code,
                duration=time.time() - start,
                timed_out=timed_out,
                error=wait_error or None,
            )
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass

    async def execute(
        self,
        command: Command,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        display = command_display(command)
        try:
            execution_context = self.prepare_context(context, env=env)
            return await asyncio.to_thread(
                self._run_sync,
                command,
                timeout,
                execution_context,
            )
        except ValueError as exc:
            return ExecutionResult(
                command=display,
                provider=self.name,
                success=False,
                stderr=str(exc),
                exit_code=-1,
                error="invalid_execution_context",
            )
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
