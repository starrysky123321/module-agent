import pytest
from pydantic import ValidationError

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.code.domain.request import CodePaperInput
from module_agent.supervision.domain import (
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationReport,
    ValidationStatus,
)
from module_agent.workflow.domain import SupervisorStep, WorkflowStatus
from module_agent.workflow.result import ModuleBuildResult


def artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=51,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Problem 51",
            implementation_steps=["Implement method"],
        ),
    )


def report(code_artifact: CodeArtifact) -> ValidationReport:
    return ValidationReport(
        literature_run_id=7,
        paper_id=code_artifact.paper_id,
        artifact_origin=code_artifact.origin,
        artifact_status=code_artifact.status,
        mode=ValidationMode.STATIC,
        status=ValidationStatus.PARTIAL,
        checks=[
            ValidationCheck(
                kind=ValidationCheckKind.REPRODUCTION_PLAN,
                status=ValidationCheckStatus.PASSED,
                summary="Reproduction plan checked",
            )
        ],
    )


def test_result_parses_complete_serialized_payload() -> None:
    code_artifact = artifact()
    paper = CodePaperInput(
        paper_id=51,
        source="openalex",
        source_id="W51",
        title="Paper 51",
    )

    result = ModuleBuildResult.model_validate(
        {
            "literature_run_id": 7,
            "status": "completed",
            "selected_paper_ids": [51],
            "selected_papers": [paper.model_dump(mode="json")],
            "code_artifacts": [
                code_artifact.model_dump(mode="json")
            ],
            "validation_reports": [
                report(code_artifact).model_dump(mode="json")
            ],
            "attempts": {
                "literature": 1,
                "code": 1,
                "validation": 2,
            },
        }
    )

    assert result.status is WorkflowStatus.COMPLETED
    assert result.selected_papers[0].paper_id == 51
    assert result.code_artifacts[0].paper_id == 51
    assert result.validation_reports[0].paper_id == 51
    assert result.attempts[SupervisorStep.VALIDATION] == 2


def test_result_accepts_early_failure_with_partial_data() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.LITERATURE,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Literature search timed out",
        retryable=False,
        attempt=2,
        error_type="TimeoutError",
    )

    result = ModuleBuildResult(
        literature_run_id=7,
        status=WorkflowStatus.FAILED,
        attempts={SupervisorStep.LITERATURE: 2},
        failure=failure,
    )

    assert result.selected_paper_ids == []
    assert result.code_artifacts == []
    assert result.failure is failure


def test_result_default_collections_are_not_shared() -> None:
    first_failure = WorkflowFailure(
        step=SupervisorStep.LITERATURE,
        category=WorkflowFailureCategory.TIMEOUT,
        message="First failed",
        retryable=False,
        attempt=1,
    )
    second_failure = WorkflowFailure(
        step=SupervisorStep.LITERATURE,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Second failed",
        retryable=False,
        attempt=1,
    )
    first = ModuleBuildResult(
        literature_run_id=1,
        status=WorkflowStatus.FAILED,
        attempts={SupervisorStep.LITERATURE: 1},
        failure=first_failure,
    )
    second = ModuleBuildResult(
        literature_run_id=2,
        status=WorkflowStatus.FAILED,
        attempts={SupervisorStep.LITERATURE: 1},
        failure=second_failure,
    )

    first.warnings.append("first only")

    assert second.warnings == []


@pytest.mark.parametrize(
    "payload",
    [
        {"literature_run_id": 0, "status": "failed"},
        {
            "literature_run_id": 7,
            "status": "failed",
            "attempts": {"validation": 0},
        },
    ],
)
def test_result_rejects_invalid_positive_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ModuleBuildResult.model_validate(payload)


def test_result_rejects_non_terminal_status() -> None:
    with pytest.raises(ValidationError, match="must be terminal"):
        ModuleBuildResult(
            literature_run_id=7,
            status=WorkflowStatus.VALIDATING,
        )


def test_completed_result_requires_all_outputs() -> None:
    with pytest.raises(ValidationError, match="requires papers"):
        ModuleBuildResult(
            literature_run_id=7,
            status=WorkflowStatus.COMPLETED,
        )


def test_completed_result_rejects_duplicate_selected_ids() -> None:
    code_artifact = artifact()
    paper = CodePaperInput(
        paper_id=51,
        source="openalex",
        source_id="W51",
        title="Paper 51",
    )

    with pytest.raises(ValidationError, match="must be unique"):
        ModuleBuildResult(
            literature_run_id=7,
            status=WorkflowStatus.COMPLETED,
            selected_paper_ids=[51, 51],
            selected_papers=[paper],
            code_artifacts=[code_artifact],
            validation_reports=[report(code_artifact)],
        )


def test_completed_result_rejects_mismatched_paper_ids() -> None:
    code_artifact = artifact()
    paper = CodePaperInput(
        paper_id=52,
        source="openalex",
        source_id="W52",
        title="Paper 52",
    )

    with pytest.raises(ValidationError, match="paper ids do not match"):
        ModuleBuildResult(
            literature_run_id=7,
            status=WorkflowStatus.COMPLETED,
            selected_paper_ids=[51],
            selected_papers=[paper],
            code_artifacts=[code_artifact],
            validation_reports=[report(code_artifact)],
        )


def test_completed_result_rejects_report_from_another_run() -> None:
    code_artifact = artifact()
    paper = CodePaperInput(
        paper_id=51,
        source="openalex",
        source_id="W51",
        title="Paper 51",
    )
    other_run_report = report(code_artifact).model_copy(
        update={"literature_run_id": 8}
    )

    with pytest.raises(ValidationError, match="does not match result"):
        ModuleBuildResult(
            literature_run_id=7,
            status=WorkflowStatus.COMPLETED,
            selected_paper_ids=[51],
            selected_papers=[paper],
            code_artifacts=[code_artifact],
            validation_reports=[other_run_report],
        )


def test_failed_result_rejects_retryable_failure() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Still retryable",
        retryable=True,
        attempt=1,
    )

    with pytest.raises(ValidationError, match="cannot be retryable"):
        ModuleBuildResult(
            literature_run_id=7,
            status=WorkflowStatus.FAILED,
            attempts={SupervisorStep.VALIDATION: 1},
            failure=failure,
        )


def test_failed_result_requires_matching_attempt_count() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Retry budget exhausted",
        retryable=False,
        attempt=2,
    )

    with pytest.raises(ValidationError, match="does not match"):
        ModuleBuildResult(
            literature_run_id=7,
            status=WorkflowStatus.FAILED,
            attempts={SupervisorStep.VALIDATION: 1},
            failure=failure,
        )
