import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.validation.application.status import (
    ValidationStatusResolver,
)
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationStatus,
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


def make_reproduction_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=2,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Reproduce the paper method",
            implementation_steps=["Implement the core algorithm"],
            inputs=["input tensor"],
            outputs=["output tensor"],
        ),
    )


def make_failed_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=3,
        origin=CodeArtifactOrigin.UNKNOWN,
        status=CodeArtifactStatus.FAILED,
        error="Code preparation failed",
    )


def make_check(status: ValidationCheckStatus) -> ValidationCheck:
    return ValidationCheck(
        kind=ValidationCheckKind.ARTIFACT_CONTRACT,
        status=status,
        summary=f"Check result: {status}",
    )


def test_status_resolver_rejects_empty_checks() -> None:
    with pytest.raises(ValueError, match="at least one check"):
        ValidationStatusResolver().resolve(make_repository_artifact(), [])


def test_failed_artifact_is_failed_even_when_check_passes() -> None:
    status = ValidationStatusResolver().resolve(
        make_failed_artifact(),
        [make_check(ValidationCheckStatus.PASSED)],
    )

    assert status is ValidationStatus.FAILED


def test_failed_check_has_priority_over_other_check_states() -> None:
    status = ValidationStatusResolver().resolve(
        make_repository_artifact(),
        [
            make_check(ValidationCheckStatus.PASSED),
            make_check(ValidationCheckStatus.WARNING),
            make_check(ValidationCheckStatus.FAILED),
        ],
    )

    assert status is ValidationStatus.FAILED


def test_complete_reproduction_plan_is_still_only_partial() -> None:
    status = ValidationStatusResolver().resolve(
        make_reproduction_artifact(),
        [make_check(ValidationCheckStatus.PASSED)],
    )

    assert status is ValidationStatus.PARTIAL


@pytest.mark.parametrize(
    "check_status",
    [ValidationCheckStatus.WARNING, ValidationCheckStatus.SKIPPED],
)
def test_warning_or_skipped_check_makes_repository_partial(
    check_status: ValidationCheckStatus,
) -> None:
    status = ValidationStatusResolver().resolve(
        make_repository_artifact(),
        [
            make_check(ValidationCheckStatus.PASSED),
            make_check(check_status),
        ],
    )

    assert status is ValidationStatus.PARTIAL


def test_ready_repository_with_only_passed_checks_is_passed() -> None:
    status = ValidationStatusResolver().resolve(
        make_repository_artifact(),
        [
            make_check(ValidationCheckStatus.PASSED),
            make_check(ValidationCheckStatus.PASSED),
        ],
    )

    assert status is ValidationStatus.PASSED
