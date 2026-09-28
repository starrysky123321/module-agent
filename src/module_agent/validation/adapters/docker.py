import asyncio
import re
from pathlib import Path, PurePosixPath
from time import perf_counter
from uuid import uuid4

from module_agent.validation.domain.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)


class DockerSandboxRunner:
    """封装 DockerSandboxRunner 相关的数据和行为。"""
    CONTAINER_REPOSITORY = PurePosixPath("/workspace/repository")
    _SENSITIVE_ASSIGNMENT = re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret|authorization)"
        r"\s*([=:])\s*([^\s,;]+)"
    )
    _BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[^\s]+")
    _SENSITIVE_FLAGS = frozenset(
        {
            "--api-key",
            "--apikey",
            "--access-token",
            "--token",
            "--password",
            "--secret",
            "--authorization",
        }
    )

    def __init__(
        self,
        allowed_root: Path,
        *,
        image: str,
        docker_executable: str = "docker",
        pids_limit: int = 128,
    ) -> None:
        """初始化当前对象。"""
        self.allowed_root = allowed_root.resolve()
        if not image.strip():
            raise ValueError("Sandbox image must be non-empty")
        if not docker_executable.strip():
            raise ValueError("Docker executable must be non-empty")
        if pids_limit <= 0:
            raise ValueError("PIDs limit must be greater than 0")
        
        self.image = image.strip()
        self.docker_executable = docker_executable.strip()
        self.pids_limit = pids_limit
        
    def _validated_repository_path(
        self,
        request: SandboxExecutionRequest,
    ) -> Path:
        repository = request.repository_path.resolve()
        
        if not repository.is_relative_to(self.allowed_root):
            raise ValueError(
                "Sandbox repository path escapes allowed root"
            )
            
        
        if not repository.is_dir():
            raise ValueError(
                "Sandbox repository path must be an existing directory"
            )
            
        return repository
    
    def _build_command(
        self,
        request: SandboxExecutionRequest,
        container_name: str,
    ) -> list[str]:
        repository = self._validated_repository_path(request)
        
        if not container_name.strip():
            raise ValueError("Container name must be non-empty")
        
        container_workdir = (
            self.CONTAINER_REPOSITORY
            / PurePosixPath(request.working_directory)
        )

        command = [
            self.docker_executable,
            "run",
            "--rm",
            "--name",
            container_name.strip(),
            "--pull",
            "never",
            "--init",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            f"{request.policy.memory_limit_mb}m",
            "--memory-swap",
            f"{request.policy.memory_limit_mb}m",
            "--cpus",
            str(request.policy.cpu_limit),
            "--mount",
            (
                f"type=bind,source={repository},"
                f"target={self.CONTAINER_REPOSITORY},readonly"
            ),
            "--workdir",
            str(container_workdir),
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,nosuid,size=512m",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        
        if not request.policy.allow_network:
            command.extend(["--network", "none"])

        if request.policy.compute_target.value == "gpu":
            command.extend(["--gpus", "all"])

        command.append(self.image)
        command.extend(request.argv)
        return command
    
    
    async def _force_remove_container(
        self,
        container_name: str,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            self.docker_executable,
            "rm",
            "--force",
            container_name.strip(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()
            
    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        
        """执行当前用例。"""
        container_name = f"module-agent-validation-{uuid4().hex}"
        command = self._build_command(request, container_name)
        started_at = perf_counter()

        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        communication = asyncio.create_task(
            self._communicate_limited(
                process,
                request.max_output_bytes,
            )
        )

        try:
            stdout, stderr, output_truncated = await asyncio.wait_for(
                asyncio.shield(communication),
                timeout=request.policy.timeout_seconds,
            )
        except TimeoutError:
            if process.returncode is None:
                process.kill()

            stdout, stderr, output_truncated = await communication
            await self._force_remove_container(container_name)

            return SandboxExecutionResult(
                exit_code=None,
                stdout=self._decode_and_redact(stdout, request.argv),
                stderr=self._decode_and_redact(stderr, request.argv),
                duration_ms=round((perf_counter() - started_at) * 1000),
                timed_out=True,
                output_truncated=output_truncated,
            )
        except BaseException:
            if process.returncode is None:
                process.kill()

            try:
                await communication
            except BaseException:
                pass

            await self._force_remove_container(container_name)
            raise

        if process.returncode is None:
            raise RuntimeError("Sandbox process completed without an exit code")

        return SandboxExecutionResult(
            exit_code=process.returncode,
            stdout=self._decode_and_redact(stdout, request.argv),
            stderr=self._decode_and_redact(stderr, request.argv),
            duration_ms=round((perf_counter() - started_at) * 1000),
            output_truncated=output_truncated,
        )

    async def _communicate_limited(
        self,
        process: asyncio.subprocess.Process,
        max_output_bytes: int,
    ) -> tuple[bytes, bytes, bool]:
        """Drain both pipes while retaining at most the configured total."""
        if max_output_bytes < 0:
            raise ValueError("Output limit cannot be negative")

        stdout_limit = (max_output_bytes + 1) // 2
        stderr_limit = max_output_bytes // 2
        stdout_result, stderr_result, _ = await asyncio.gather(
            self._read_stream_limited(process.stdout, stdout_limit),
            self._read_stream_limited(process.stderr, stderr_limit),
            process.wait(),
        )
        stdout, stdout_truncated = stdout_result
        stderr, stderr_truncated = stderr_result
        return stdout, stderr, stdout_truncated or stderr_truncated

    @classmethod
    def _decode_and_redact(
        cls,
        output: bytes,
        argv: list[str],
    ) -> str:
        text = output.decode("utf-8", errors="replace")

        for value in sorted(
            cls._sensitive_argument_values(argv),
            key=len,
            reverse=True,
        ):
            text = text.replace(value, "[REDACTED]")

        text = cls._BEARER_TOKEN.sub("Bearer [REDACTED]", text)
        return cls._SENSITIVE_ASSIGNMENT.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}[REDACTED]"
            ),
            text,
        )

    @classmethod
    def _sensitive_argument_values(cls, argv: list[str]) -> set[str]:
        values: set[str] = set()
        index = 0
        while index < len(argv):
            argument = argv[index]
            normalized = argument.casefold()
            if normalized in cls._SENSITIVE_FLAGS and index + 1 < len(argv):
                if argv[index + 1]:
                    values.add(argv[index + 1])
                index += 2
                continue

            for flag in cls._SENSITIVE_FLAGS:
                prefix = f"{flag}="
                if normalized.startswith(prefix):
                    value = argument[len(prefix):]
                    if value:
                        values.add(value)
                    break
            index += 1

        return values

    @staticmethod
    async def _read_stream_limited(
        stream: asyncio.StreamReader | None,
        limit: int,
    ) -> tuple[bytes, bool]:
        if limit < 0:
            raise ValueError("Output limit cannot be negative")

        if stream is None:
            return b"", False
        
        chunks: list[bytes] = []
        remaining = limit
        truncated = False
        
        while True:
            chunk = await stream.read(8192)

            if not chunk:
                break
        
            kept_length = min(len(chunk), remaining)
            
            if kept_length:
                chunks.append(chunk[:kept_length])
                remaining -= kept_length
            
            if kept_length < len(chunk):
                truncated = True
        
        return b"".join(chunks), truncated
