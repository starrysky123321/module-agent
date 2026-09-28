import asyncio
from pathlib import Path
import subprocess
import sys

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.python_syntax import (
    PythonSyntaxCheck,
)
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)
from module_agent.validation.domain.report import (
    ValidationCheckKind,
    ValidationCheckStatus,
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
    return ValidationPolicy(
        mode=ValidationMode.SANDBOX,
        timeout_seconds=30,
    )


def make_repository_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha="abcdef1",
        local_path="/workspace/run-1/paper-1/repository",
    )


def result(
    *,
    exit_code: int | None = 0,
    stdout: str = "checked=2\n",
    stderr: str = "",
    timed_out: bool = False,
    output_truncated: bool = False,
) -> SandboxExecutionResult:
    return SandboxExecutionResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=12,
        timed_out=timed_out,
        output_truncated=output_truncated,
    )


def test_python_syntax_check_requires_sandbox_policy() -> None:
    with pytest.raises(ValueError, match="requires sandbox"):
        PythonSyntaxCheck(
            FakeSandboxRunner(result()),
            ValidationPolicy(mode=ValidationMode.STATIC),
        )


def test_python_syntax_check_builds_safe_sandbox_request() -> None:
    runner = FakeSandboxRunner(result())
    check = PythonSyntaxCheck(runner, sandbox_policy())

    check_result = asyncio.run(check.run(make_repository_artifact()))

    assert len(runner.calls) == 1
    request = runner.calls[0]
    assert request.repository_path == Path(
        "/workspace/run-1/paper-1/repository"
    )
    assert request.argv == ["python", "-c", check.SYNTAX_SCRIPT]
    assert check_result.kind is ValidationCheckKind.SYNTAX
    assert check_result.status is ValidationCheckStatus.PASSED
    assert check_result.command == "python -c <syntax-check>"
    assert check_result.exit_code == 0
    assert check_result.duration_ms == 12


def test_python_syntax_check_reports_syntax_failure() -> None:
    runner = FakeSandboxRunner(
        result(exit_code=1, stderr="broken.py: invalid syntax")
    )
    check = PythonSyntaxCheck(runner, sandbox_policy())

    check_result = asyncio.run(check.run(make_repository_artifact()))

    assert check_result.status is ValidationCheckStatus.FAILED
    assert check_result.details["stderr"] == "broken.py: invalid syntax"


def test_python_syntax_check_reports_timeout() -> None:
    runner = FakeSandboxRunner(
        result(
            exit_code=None,
            stdout="",
            timed_out=True,
        )
    )
    check = PythonSyntaxCheck(runner, sandbox_policy())

    check_result = asyncio.run(check.run(make_repository_artifact()))

    assert check_result.status is ValidationCheckStatus.FAILED
    assert check_result.summary == "Python syntax check timed out"
    assert check_result.exit_code is None


def test_python_syntax_check_skips_repository_without_python_files() -> None:
    runner = FakeSandboxRunner(result(stdout="checked=0\n"))
    check = PythonSyntaxCheck(runner, sandbox_policy())

    check_result = asyncio.run(check.run(make_repository_artifact()))

    assert check_result.status is ValidationCheckStatus.SKIPPED


def test_python_syntax_check_preserves_truncation_evidence() -> None:
    runner = FakeSandboxRunner(result(output_truncated=True))
    check = PythonSyntaxCheck(runner, sandbox_policy())

    check_result = asyncio.run(check.run(make_repository_artifact()))

    assert check_result.details["output_truncated"] is True


def test_python_syntax_check_does_not_run_without_local_path() -> None:
    runner = FakeSandboxRunner(result())
    check = PythonSyntaxCheck(runner, sandbox_policy())
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
    )

    check_result = asyncio.run(check.run(malformed_artifact))

    assert runner.calls == []
    assert check_result.status is ValidationCheckStatus.FAILED


def test_syntax_script_compiles_valid_source_without_executing_it(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed.txt"
    source = tmp_path / "module.py"
    source.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-c", PythonSyntaxCheck.SYNTAX_SCRIPT],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == "checked=1\n"
    assert marker.exists() is False


def test_syntax_script_reports_invalid_source(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-c", PythonSyntaxCheck.SYNTAX_SCRIPT],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stdout == "checked=1\n"
    assert "broken.py" in completed.stderr
