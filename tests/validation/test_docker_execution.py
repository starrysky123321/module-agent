import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from module_agent.validation.adapters import docker as docker_module
from module_agent.validation.adapters.docker import DockerSandboxRunner
from module_agent.validation.domain.ports import SandboxRunner
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import SandboxExecutionRequest


WaitResult = int | BaseException


class FakeStream:
    def __init__(
        self,
        chunks: list[bytes] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.chunks = list(chunks or []) + [b""]
        self.error = error

    async def read(self, _: int = -1) -> bytes:
        if self.error is not None:
            error = self.error
            self.error = None
            raise error
        return self.chunks.pop(0)


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        stream_error: BaseException | None = None,
        wait_results: list[WaitResult] | None = None,
        completion_returncode: int = 0,
        hangs: bool = False,
    ) -> None:
        self.stdout = cast(
            asyncio.StreamReader,
            FakeStream([stdout], stream_error),
        )
        self.stderr = cast(asyncio.StreamReader, FakeStream([stderr]))
        self.wait_results = list(wait_results or [])
        self.completion_returncode = completion_returncode
        self.hangs = hangs
        self.returncode: int | None = None
        self.killed = False

    async def wait(self) -> int:
        if self.wait_results:
            result = self.wait_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            self.returncode = result
            return result

        while self.hangs and not self.killed:
            await asyncio.sleep(0)

        if self.returncode is None:
            self.returncode = self.completion_returncode
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeProcessFactory:
    def __init__(self, processes: list[FakeProcess]) -> None:
        self.processes = list(processes)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> FakeProcess:
        self.calls.append((args, kwargs))
        return self.processes.pop(0)


def make_request(repository: Path) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        repository_path=repository,
        argv=["python", "--version"],
        policy=ValidationPolicy(
            mode=ValidationMode.SANDBOX,
            timeout_seconds=5,
        ),
    )


def fixed_container_name(monkeypatch: pytest.MonkeyPatch) -> str:
    class FixedUuid:
        hex = "abc123"

    monkeypatch.setattr(docker_module, "uuid4", lambda: FixedUuid())
    return "module-agent-validation-abc123"


def install_process_factory(
    monkeypatch: pytest.MonkeyPatch,
    factory: FakeProcessFactory,
) -> None:
    replacement: Any = factory
    monkeypatch.setattr(
        docker_module.asyncio,
        "create_subprocess_exec",
        replacement,
    )


def test_docker_runner_satisfies_sandbox_port(tmp_path: Path) -> None:
    runner: SandboxRunner = DockerSandboxRunner(
        tmp_path,
        image="sandbox:local",
    )

    assert isinstance(runner, DockerSandboxRunner)


def test_execute_returns_completed_process_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    process = FakeProcess(
        stdout=b"Python 3\n",
        completion_returncode=0,
    )
    factory = FakeProcessFactory([process])
    install_process_factory(monkeypatch, factory)
    container_name = fixed_container_name(monkeypatch)
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    result = asyncio.run(runner.execute(make_request(repository)))

    command = factory.calls[0][0]
    assert command[:2] == ("docker", "run")
    assert command[command.index("--name") + 1] == container_name
    assert result.exit_code == 0
    assert result.stdout == "Python 3\n"
    assert result.stderr == ""
    assert result.timed_out is False
    assert process.killed is False
    assert len(factory.calls) == 1


def test_execute_preserves_nonzero_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    process = FakeProcess(
        stderr=b"syntax error\n",
        completion_returncode=2,
    )
    factory = FakeProcessFactory([process])
    install_process_factory(monkeypatch, factory)
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    result = asyncio.run(runner.execute(make_request(repository)))

    assert result.exit_code == 2
    assert result.stderr == "syntax error\n"
    assert result.timed_out is False


def test_execute_kills_cli_and_removes_container_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    main_process = FakeProcess(
        stdout=b"partial",
        stderr=b"timed out",
        hangs=True,
    )
    cleanup_process = FakeProcess(wait_results=[0])
    factory = FakeProcessFactory([main_process, cleanup_process])
    install_process_factory(monkeypatch, factory)
    container_name = fixed_container_name(monkeypatch)
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    real_wait_for = asyncio.wait_for

    async def timeout_execution(awaitable: Any, timeout: float):
        if timeout == 5:
            await asyncio.sleep(0)
            raise TimeoutError
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(docker_module.asyncio, "wait_for", timeout_execution)

    result = asyncio.run(runner.execute(make_request(repository)))

    assert main_process.killed is True
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.stdout == "partial"
    assert factory.calls[1][0] == (
        "docker",
        "rm",
        "--force",
        container_name,
    )


@pytest.mark.parametrize(
    "execution_error",
    [RuntimeError("Docker communication failed"), asyncio.CancelledError()],
)
def test_execute_removes_container_and_reraises_unexpected_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_error: BaseException,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    main_process = FakeProcess(
        stream_error=execution_error,
        hangs=True,
    )
    cleanup_process = FakeProcess(wait_results=[0])
    factory = FakeProcessFactory([main_process, cleanup_process])
    install_process_factory(monkeypatch, factory)
    container_name = fixed_container_name(monkeypatch)
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    with pytest.raises(type(execution_error)):
        asyncio.run(runner.execute(make_request(repository)))

    assert main_process.killed is True
    assert factory.calls[1][0] == (
        "docker",
        "rm",
        "--force",
        container_name,
    )


def test_force_remove_kills_cleanup_process_when_cleanup_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_process = FakeProcess(
        wait_results=[TimeoutError(), -9],
    )
    factory = FakeProcessFactory([cleanup_process])
    install_process_factory(monkeypatch, factory)
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    asyncio.run(runner._force_remove_container("validation-test"))

    assert cleanup_process.killed is True
    assert factory.calls[0][0] == (
        "docker",
        "rm",
        "--force",
        "validation-test",
    )
