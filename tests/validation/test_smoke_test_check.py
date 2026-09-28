import asyncio
from pathlib import Path

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.smoke_test import SmokeTestCheck
from module_agent.validation.domain.report import (
    ValidationCheckKind,
    ValidationCheckStatus,
)
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)


class FakeSandboxRunner:
    def __init__(self, result: SandboxExecutionResult) -> None:
        self.result = result
        self.calls: list[SandboxExecutionRequest] = []

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        self.calls.append(request)
        return self.result


def sandbox_policy() -> ValidationPolicy:
    return ValidationPolicy(mode=ValidationMode.SANDBOX)


def execution_result(
    *,
    exit_code: int | None = 0,
    stdout: str = "usage: package\n",
    stderr: str = "",
    timed_out: bool = False,
) -> SandboxExecutionResult:
    return SandboxExecutionResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=30,
        timed_out=timed_out,
    )


def repository_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha="abcdef1",
        local_path="/workspace/repository",
    )


def test_smoke_check_requires_sandbox_mode_and_command() -> None:
    runner = FakeSandboxRunner(execution_result())

    with pytest.raises(ValueError, match="sandbox validation mode"):
        SmokeTestCheck(
            runner,
            ValidationPolicy(mode=ValidationMode.STATIC),
            ["python", "--version"],
        )
    with pytest.raises(ValueError, match="requires a command"):
        SmokeTestCheck(runner, sandbox_policy(), [])


def test_smoke_check_passes_exact_argv_and_working_directory() -> None:
    runner = FakeSandboxRunner(execution_result())
    check = SmokeTestCheck(
        runner,
        sandbox_policy(),
        ["python", "-m", "package", "--help"],
        working_directory="examples",
    )

    result = asyncio.run(check.run(repository_artifact()))

    request = runner.calls[0]
    assert request.repository_path == Path("/workspace/repository")
    assert request.argv == ["python", "-m", "package", "--help"]
    assert request.working_directory == "examples"
    assert result.kind is ValidationCheckKind.SMOKE_TEST
    assert result.status is ValidationCheckStatus.PASSED
    assert result.exit_code == 0
    assert result.duration_ms == 30


def test_smoke_check_does_not_expose_arguments_in_command_summary() -> None:
    runner = FakeSandboxRunner(execution_result())
    check = SmokeTestCheck(
        runner,
        sandbox_policy(),
        ["python", "--token", "secret-value"],
    )

    result = asyncio.run(check.run(repository_artifact()))

    assert result.command == "python <smoke-test-arguments>"
    assert "secret-value" not in result.command
    assert "secret-value" not in str(result.details)


def test_smoke_check_reports_nonzero_exit() -> None:
    runner = FakeSandboxRunner(
        execution_result(exit_code=2, stdout="", stderr="bad input")
    )
    check = SmokeTestCheck(runner, sandbox_policy(), ["python", "example.py"])

    result = asyncio.run(check.run(repository_artifact()))

    assert result.status is ValidationCheckStatus.FAILED
    assert result.details["stderr"] == "bad input"


def test_smoke_check_reports_timeout() -> None:
    runner = FakeSandboxRunner(
        execution_result(exit_code=None, stdout="", timed_out=True)
    )
    check = SmokeTestCheck(runner, sandbox_policy(), ["python", "example.py"])

    result = asyncio.run(check.run(repository_artifact()))

    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Smoke test timed out"


def test_smoke_check_does_not_execute_without_local_path() -> None:
    runner = FakeSandboxRunner(execution_result())
    check = SmokeTestCheck(runner, sandbox_policy(), ["python", "example.py"])
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert runner.calls == []
    assert result.status is ValidationCheckStatus.FAILED
