import pytest
from pydantic import ValidationError

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.domain.request import (
    SandboxValidationOptions,
    ValidationMode,
    ValidationPolicy,
    ValidationRequest,
)


def failed_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.UNKNOWN,
        status=CodeArtifactStatus.FAILED,
        error="Code preparation failed",
    )


def test_sandbox_options_have_safe_defaults() -> None:
    options = SandboxValidationOptions()

    assert options.import_modules == []
    assert options.smoke_test_argv is None
    assert options.smoke_test_working_directory == "."


def test_sandbox_options_normalize_valid_import_modules() -> None:
    options = SandboxValidationOptions(
        import_modules=[" package ", "package.models.encoder"],
    )

    assert options.import_modules == ["package", "package.models.encoder"]


@pytest.mark.parametrize(
    "module",
    ["", "   ", "../outside", "package-name", "package;command", "class", "a..b"],
)
def test_sandbox_options_reject_invalid_import_module(module: str) -> None:
    with pytest.raises(ValidationError, match="Invalid Python import module"):
        SandboxValidationOptions(import_modules=[module])


def test_sandbox_options_reject_duplicate_normalized_modules() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        SandboxValidationOptions(import_modules=["package", " package "])


def test_sandbox_options_limit_import_module_count() -> None:
    with pytest.raises(ValidationError):
        SandboxValidationOptions(
            import_modules=[f"package{index}" for index in range(21)]
        )


def test_sandbox_options_allow_empty_non_executable_argument() -> None:
    options = SandboxValidationOptions(
        smoke_test_argv=["python", "-c", ""],
    )

    assert options.smoke_test_argv == ["python", "-c", ""]


def test_sandbox_options_reject_blank_smoke_executable() -> None:
    with pytest.raises(ValidationError, match="executable must be non-empty"):
        SandboxValidationOptions(smoke_test_argv=["  ", "--version"])


def test_sandbox_options_reject_null_byte_in_smoke_argument() -> None:
    with pytest.raises(ValidationError, match="null bytes"):
        SandboxValidationOptions(
            smoke_test_argv=["python", "bad\x00argument"]
        )


@pytest.mark.parametrize(
    "working_directory",
    ["/etc", "../outside", "src/../../outside", "bad\x00path"],
)
def test_sandbox_options_reject_unsafe_smoke_working_directory(
    working_directory: str,
) -> None:
    with pytest.raises(ValidationError):
        SandboxValidationOptions(
            smoke_test_argv=["python", "--version"],
            smoke_test_working_directory=working_directory,
        )


def test_sandbox_options_require_command_for_custom_working_directory() -> None:
    with pytest.raises(ValidationError, match="requires smoke_test_argv"):
        SandboxValidationOptions(smoke_test_working_directory="examples")


def test_static_request_rejects_even_empty_sandbox_options() -> None:
    with pytest.raises(ValidationError, match="cannot include sandbox options"):
        ValidationRequest(
            literature_run_id=1,
            artifacts=[failed_artifact()],
            policy=ValidationPolicy(mode=ValidationMode.STATIC),
            sandbox_options=SandboxValidationOptions(),
        )


def test_sandbox_request_accepts_explicit_options() -> None:
    options = SandboxValidationOptions(
        import_modules=["package"],
        smoke_test_argv=["python", "-m", "package", "--help"],
    )

    request = ValidationRequest(
        literature_run_id=1,
        artifacts=[failed_artifact()],
        policy=ValidationPolicy(mode=ValidationMode.SANDBOX),
        sandbox_options=options,
    )

    assert request.sandbox_options is options


def test_sandbox_request_does_not_require_optional_code_execution() -> None:
    request = ValidationRequest(
        literature_run_id=1,
        artifacts=[failed_artifact()],
        policy=ValidationPolicy(mode=ValidationMode.SANDBOX),
    )

    assert request.sandbox_options is None
