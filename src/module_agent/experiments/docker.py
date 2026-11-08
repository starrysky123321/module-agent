"""Operator-side Docker executor. Never exposes the Docker socket to paper code."""

import asyncio
import hashlib
import os
from pathlib import Path
import stat
from time import perf_counter
from typing import Literal, cast
from uuid import uuid4

from module_agent.experiments.domain import ExperimentPlan, StepResult
from module_agent.experiments.workspace import ExperimentWorkspace
from module_agent.validation.adapters.docker import DockerSandboxRunner


class DockerExperimentRunner:
    def __init__(self, workspace: ExperimentWorkspace) -> None:
        self.workspace = workspace

    def command(
        self, plan: ExperimentPlan, argv: list[str], container: str
    ) -> list[str]:
        run = self.workspace.run_directory(plan)
        uid, gid = (65534, 65534) if os.getuid() == 0 else (os.getuid(), os.getgid())
        command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container,
            "--init",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--network",
            "none",
            "--pids-limit",
            "128",
            "--memory",
            f"{plan.budget.memory_mb}m",
            "--memory-swap",
            f"{plan.budget.memory_mb}m",
            "--cpus",
            str(plan.budget.cpu_limit),
            "--user",
            f"{uid}:{gid}",
            "--tmpfs",
            f"/tmp:rw,nosuid,size={plan.budget.temporary_mb}m",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "CUDA_VISIBLE_DEVICES=0",
            "--env",
            "OMP_NUM_THREADS=2",
            "--label",
            "module-agent.experiment.workspace="
            + hashlib.sha256(str(self.workspace.root).encode()).hexdigest(),
            "--label",
            "module-agent.experiment.plan=" + str(plan.id),
            "--gpus",
            f'"device={plan.budget.gpu_uuid}"',
            "--workdir",
            "/workspace/repository/code",
        ]
        for source, target, readonly in (
            (run / "repository", "/workspace/repository", True),
            (run / "data", "/workspace/repository/data", True),
            (run / "outputs", "/workspace/repository/logs", False),
        ):
            if any(char in str(source) for char in (",", "\n", "\x00")):
                raise ValueError("Docker mount source contains unsupported characters")
            command += [
                "--mount",
                f"type=bind,source={source},target={target}"
                + (",readonly" if readonly else ""),
            ]
        return [*command, plan.image, *argv]

    async def _remove(self, name: str) -> None:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "--force",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise RuntimeError(
                "Sandbox cleanup timed out; inspect owned container " + name
            ) from error
        if process.returncode:
            check = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "-a",
                "-q",
                "--filter",
                "name=^/" + name + "$",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                stdout, _ = await asyncio.wait_for(check.communicate(), 10)
            except BaseException:
                if check.returncode is None:
                    check.kill()
                    await check.wait()
                raise
            if check.returncode or stdout.strip():
                raise RuntimeError(
                    "Sandbox cleanup could not be verified; inspect owned container "
                    + name
                )

    @staticmethod
    def _check_output_limit(directory: Path, maximum: int) -> None:
        total = count = 0
        for root, directories, files in os.walk(directory, followlinks=False):
            for name in directories + files:
                path = Path(root) / name
                info = path.lstat()
                count += 1
                if path.is_symlink() or count > 10000:
                    raise ValueError("Output contains symlinks or too many files")
                total += info.st_size
                if total > maximum:
                    raise ValueError("Experiment output space budget exceeded")

    async def execute(
        self, plan: ExperimentPlan, name: str, argv: list[str]
    ) -> StepResult:
        if name not in {"environment", "train", "evaluate"}:
            raise ValueError("Unknown experiment step")
        owned = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=module-agent.experiment.workspace="
            + hashlib.sha256(str(self.workspace.root).encode()).hexdigest(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(owned.communicate(), 10)
        except BaseException:
            if owned.returncode is None:
                owned.kill()
                await owned.wait()
            raise
        if owned.returncode or stdout.strip():
            raise RuntimeError(
                "Docker is unavailable or a previous owned experiment container still runs; inspect it before starting another"
            )
        container = "module-agent-experiment-" + uuid4().hex
        started = perf_counter()
        log_path = self.workspace.run_directory(plan) / "execution.log"
        log_fd = os.open(
            log_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        if not stat.S_ISREG(os.fstat(log_fd).st_mode):
            os.close(log_fd)
            raise ValueError("Experiment log must be a regular file")
        log = os.fdopen(log_fd, "ab", buffering=0)
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command(plan, argv, container),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except BaseException:
            log.close()
            await self._remove(container)
            raise
        log_remaining = max(0, 1_048_576 - log_path.stat().st_size)
        log_truncated = False

        def append_line(line: bytes, channel: str):
            nonlocal log_remaining, log_truncated
            safe = DockerSandboxRunner._decode_and_redact(line, argv)
            data = f"[{name}/{channel}] {safe}\n".encode()
            log.write(data[:log_remaining])
            if len(data) > log_remaining:
                log_truncated = True
            log_remaining = max(0, log_remaining - len(data))

        async def read_stream(stream: asyncio.StreamReader | None, channel: str):
            captured = bytearray()
            pending = bytearray()
            truncated = dropping = False
            if stream is not None:
                while chunk := await stream.read(8192):
                    remaining = max(0, 131072 - len(captured))
                    captured.extend(chunk[:remaining])
                    truncated = truncated or len(chunk) > remaining
                    for part in chunk.splitlines(keepends=True):
                        if not dropping:
                            pending.extend(part)
                            if len(pending) > 8192:
                                append_line(b"[overlong log line omitted]", channel)
                                pending.clear()
                                dropping = True
                        if part.endswith((b"\n", b"\r")):
                            if pending:
                                append_line(bytes(pending).rstrip(b"\r\n"), channel)
                            pending.clear()
                            dropping = False
                if pending:
                    append_line(bytes(pending), channel)
            return bytes(captured), truncated

        async def collect():
            return await asyncio.gather(
                read_stream(process.stdout, "stdout"),
                read_stream(process.stderr, "stderr"),
                process.wait(),
            )

        communication = asyncio.create_task(collect())
        try:
            while not communication.done():
                await asyncio.wait({communication}, timeout=0.2)
                self._check_output_limit(
                    self.workspace.run_directory(plan) / "outputs",
                    plan.budget.output_mb * 1024 * 1024,
                )
            stdout, stderr, _ = await communication
            assert process.returncode is not None
            result = StepResult(
                name=cast(Literal["environment", "train", "evaluate"], name),
                exit_code=process.returncode,
                stdout=DockerSandboxRunner._decode_and_redact(stdout[0], argv),
                stderr=DockerSandboxRunner._decode_and_redact(stderr[0], argv),
                duration_ms=round((perf_counter() - started) * 1000),
                output_truncated=stdout[1] or stderr[1] or log_truncated,
            )
            return result
        finally:
            # Remove the owned container before waiting for pipe EOF on cancellation.
            try:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await self._remove(container)
            finally:
                if not communication.done():
                    communication.cancel()
                await asyncio.gather(communication, return_exceptions=True)
                log.close()
