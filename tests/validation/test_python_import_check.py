import asyncio
from pathlib import Path

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.python_import import (
    PythonImportCheck,
)
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
    stdout: str = "imported=2\nfailed=0\n",
    stderr: str = "",
    timed_out: bool = False,
) -> SandboxExecutionResult:
    return SandboxExecutionResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=20,
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


def test_import_check_requires_sandbox_mode_and_modules() -> None:
    runner = FakeSandboxRunner(execution_result())

    with pytest.raises(ValueError, match="sandbox validation mode"):
        PythonImportCheck(
            runner,
            ValidationPolicy(mode=ValidationMode.STATIC),
            ["package"],
        )
    with pytest.raises(ValueError, match="at least one module"):
        PythonImportCheck(runner, sandbox_policy(), [])


def test_import_check_copies_module_sequence() -> None:
    modules = ["package"]
    check = PythonImportCheck(
        FakeSandboxRunner(execution_result()),
        sandbox_policy(),
        modules,
    )

    modules.append("changed_after_construction")

    assert check.modules == ("package",)


def test_import_check_builds_request_for_only_approved_modules() -> None:
    runner = FakeSandboxRunner(execution_result())
    check = PythonImportCheck(
        runner,
        sandbox_policy(),
        ["package", "package.model"],
    )

    result = asyncio.run(check.run(repository_artifact()))

    request = runner.calls[0]
    assert request.repository_path == Path("/workspace/repository")
    assert request.argv == [
        "python",
        "-c",
        check.IMPORT_SCRIPT,
        "package",
        "package.model",
    ]
    assert result.kind is ValidationCheckKind.IMPORT
    assert result.status is ValidationCheckStatus.PASSED
    assert result.command == (
        "python -c <import-check> package package.model"
    )
    assert result.exit_code == 0
    assert result.duration_ms == 20


def test_import_check_reports_failed_import() -> None:
    runner = FakeSandboxRunner(
        execution_result(
            exit_code=1,
            stdout="imported=0\nfailed=1\n",
            stderr="package: ModuleNotFoundError",
        )
    )
    check = PythonImportCheck(runner, sandbox_policy(), ["package"])

    result = asyncio.run(check.run(repository_artifact()))

    assert result.status is ValidationCheckStatus.FAILED
    assert result.details["stderr"] == "package: ModuleNotFoundError"


def test_import_check_reports_timeout() -> None:
    runner = FakeSandboxRunner(
        execution_result(exit_code=None, stdout="", timed_out=True)
    )
    check = PythonImportCheck(runner, sandbox_policy(), ["package"])

    result = asyncio.run(check.run(repository_artifact()))

    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Python import check timed out"


def test_import_check_does_not_execute_without_local_path() -> None:
    runner = FakeSandboxRunner(execution_result())
    check = PythonImportCheck(runner, sandbox_policy(), ["package"])
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert runner.calls == []
    assert result.status is ValidationCheckStatus.FAILED


def test_import_script_is_valid_python() -> None:
    compile(PythonImportCheck.IMPORT_SCRIPT, "<import-check>", "exec")
