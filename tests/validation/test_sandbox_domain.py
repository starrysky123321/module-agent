from pathlib import Path

import pytest
from pydantic import ValidationError

from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)


def sandbox_policy() -> ValidationPolicy:
    return ValidationPolicy(mode=ValidationMode.SANDBOX)


def test_sandbox_request_accepts_safe_command() -> None:
    request = SandboxExecutionRequest(
        repository_path=Path("/workspace/repository"),
        argv=["python", "-c", ""],
        working_directory="examples/demo",
        policy=sandbox_policy(),
    )

    assert request.argv == ["python", "-c", ""]
    assert request.working_directory == "examples/demo"
    assert request.max_output_bytes == 65_536


def test_sandbox_request_rejects_static_policy() -> None:
    with pytest.raises(ValidationError, match="requires sandbox mode"):
        SandboxExecutionRequest(
            repository_path=Path("/workspace/repository"),
            argv=["python", "--version"],
            policy=ValidationPolicy(mode=ValidationMode.STATIC),
        )


def test_sandbox_request_rejects_relative_repository_path() -> None:
    with pytest.raises(ValidationError, match="must be absolute"):
        SandboxExecutionRequest(
            repository_path=Path("relative/repository"),
            argv=["python", "--version"],
            policy=sandbox_policy(),
        )


@pytest.mark.parametrize(
    "working_directory",
    ["/etc", "../outside", "src/../../outside"],
)
def test_sandbox_request_rejects_working_directory_escape(
    working_directory: str,
) -> None:
    with pytest.raises(ValidationError, match="stay inside repository"):
        SandboxExecutionRequest(
            repository_path=Path("/workspace/repository"),
            argv=["python", "--version"],
            working_directory=working_directory,
            policy=sandbox_policy(),
        )


def test_sandbox_request_rejects_empty_argv() -> None:
    with pytest.raises(ValidationError):
        SandboxExecutionRequest(
            repository_path=Path("/workspace/repository"),
            argv=[],
            policy=sandbox_policy(),
        )


def test_sandbox_request_rejects_blank_executable() -> None:
    with pytest.raises(ValidationError, match="executable must be non-empty"):
        SandboxExecutionRequest(
            repository_path=Path("/workspace/repository"),
            argv=["   ", "--version"],
            policy=sandbox_policy(),
        )


def test_sandbox_request_rejects_null_byte_in_any_argument() -> None:
    with pytest.raises(ValidationError, match="null bytes"):
        SandboxExecutionRequest(
            repository_path=Path("/workspace/repository"),
            argv=["python", "bad\x00argument"],
            policy=sandbox_policy(),
        )


@pytest.mark.parametrize("max_output_bytes", [1023, 1_048_577])
def test_sandbox_request_limits_output_size(max_output_bytes: int) -> None:
    with pytest.raises(ValidationError):
        SandboxExecutionRequest(
            repository_path=Path("/workspace/repository"),
            argv=["python", "--version"],
            policy=sandbox_policy(),
            max_output_bytes=max_output_bytes,
        )


def test_completed_sandbox_result_requires_exit_code() -> None:
    with pytest.raises(ValidationError, match="requires an exit code"):
        SandboxExecutionResult(duration_ms=5)


def test_completed_sandbox_result_accepts_exit_code() -> None:
    result = SandboxExecutionResult(
        exit_code=0,
        stdout="Python 3",
        duration_ms=5,
    )

    assert result.exit_code == 0
    assert result.timed_out is False


def test_timed_out_sandbox_result_may_have_no_exit_code() -> None:
    result = SandboxExecutionResult(
        duration_ms=1000,
        timed_out=True,
        stderr="Command timed out",
    )

    assert result.exit_code is None
    assert result.timed_out is True


def test_sandbox_result_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        SandboxExecutionResult(exit_code=0, duration_ms=-1)
