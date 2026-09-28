"""Validation domain contract tests."""

import pytest
from pydantic import ValidationError

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationPolicy,
    ValidationReport,
    ValidationRequest,
    ValidationStatus,
)


def _repository_artifact(paper_id: int = 1) -> CodeArtifact:
    return CodeArtifact(
        paper_id=paper_id,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha="abcdef1",
        local_path=f"/workspace/{paper_id}",
    )


def _reproduction_artifact(paper_id: int = 2) -> CodeArtifact:
    return CodeArtifact(
        paper_id=paper_id,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Reproduce the paper method",
            implementation_steps=["Implement the core algorithm"],
        ),
    )


def _check(
    status: ValidationCheckStatus = ValidationCheckStatus.PASSED,
) -> ValidationCheck:
    return ValidationCheck(
        kind=ValidationCheckKind.ARTIFACT_CONTRACT,
        status=status,
        summary="Artifact contract checked",
    )


def test_validation_request_uses_safe_defaults_and_normalizes_text() -> None:
    request = ValidationRequest(
        literature_run_id=7,
        artifacts=[_repository_artifact()],
        user_requirements="  validate the public API  ",
    )

    assert request.policy.mode is ValidationMode.STATIC
    assert request.policy.allow_network is False
    assert request.user_requirements == "validate the public API"


def test_validation_request_turns_blank_requirements_into_none() -> None:
    request = ValidationRequest(
        literature_run_id=7,
        artifacts=[_repository_artifact()],
        user_requirements="   ",
    )

    assert request.user_requirements is None


def test_validation_request_rejects_duplicate_paper_artifacts() -> None:
    with pytest.raises(ValidationError, match="unique paper ids"):
        ValidationRequest(
            literature_run_id=7,
            artifacts=[
                _repository_artifact(paper_id=1),
                _reproduction_artifact(paper_id=1),
            ],
        )


def test_static_policy_cannot_enable_network() -> None:
    with pytest.raises(ValidationError, match="cannot enable network"):
        ValidationPolicy(
            mode=ValidationMode.STATIC,
            allow_network=True,
        )


def test_sandbox_policy_carries_resource_limits() -> None:
    policy = ValidationPolicy(
        mode=ValidationMode.SANDBOX,
        allow_network=False,
        timeout_seconds=120,
        memory_limit_mb=2048,
        cpu_limit=2.0,
    )

    assert policy.timeout_seconds == 120
    assert policy.memory_limit_mb == 2048
    assert policy.cpu_limit == 2.0


def test_static_passed_report_is_valid_without_code_execution() -> None:
    report = ValidationReport(
        literature_run_id=7,
        paper_id=1,
        artifact_origin=CodeArtifactOrigin.AUTHOR,
        artifact_status=CodeArtifactStatus.REPOSITORY_READY,
        mode=ValidationMode.STATIC,
        status=ValidationStatus.PASSED,
        checks=[_check()],
    )

    assert report.code_executed is False
    assert report.status is ValidationStatus.PASSED


def test_static_report_cannot_claim_code_execution() -> None:
    with pytest.raises(ValidationError, match="cannot execute artifact code"):
        ValidationReport(
            literature_run_id=7,
            paper_id=1,
            artifact_origin=CodeArtifactOrigin.AUTHOR,
            artifact_status=CodeArtifactStatus.REPOSITORY_READY,
            mode=ValidationMode.STATIC,
            status=ValidationStatus.PARTIAL,
            checks=[_check(ValidationCheckStatus.WARNING)],
            code_executed=True,
        )


def test_passed_report_cannot_contain_failed_check() -> None:
    with pytest.raises(ValidationError, match="cannot contain failures"):
        ValidationReport(
            literature_run_id=7,
            paper_id=1,
            artifact_origin=CodeArtifactOrigin.AUTHOR,
            artifact_status=CodeArtifactStatus.REPOSITORY_READY,
            mode=ValidationMode.SANDBOX,
            status=ValidationStatus.PASSED,
            checks=[_check(ValidationCheckStatus.FAILED)],
            code_executed=True,
        )


def test_failed_report_requires_failure_evidence() -> None:
    with pytest.raises(
        ValidationError,
        match="requires a failed check or error",
    ):
        ValidationReport(
            literature_run_id=7,
            paper_id=1,
            artifact_origin=CodeArtifactOrigin.AUTHOR,
            artifact_status=CodeArtifactStatus.REPOSITORY_READY,
            mode=ValidationMode.STATIC,
            status=ValidationStatus.FAILED,
            checks=[_check()],
        )


def test_failed_report_accepts_structured_failure_evidence() -> None:
    report = ValidationReport(
        literature_run_id=7,
        paper_id=1,
        artifact_origin=CodeArtifactOrigin.AUTHOR,
        artifact_status=CodeArtifactStatus.REPOSITORY_READY,
        mode=ValidationMode.SANDBOX,
        status=ValidationStatus.FAILED,
        checks=[_check(ValidationCheckStatus.FAILED)],
        code_executed=True,
    )

    assert report.status is ValidationStatus.FAILED
