import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.supervision.application.state_validator import (
    WorkflowStateValidator,
)
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
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)


def artifact(paper_id: int = 1) -> CodeArtifact:
    return CodeArtifact(
        paper_id=paper_id,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem=f"Problem {paper_id}",
            implementation_steps=["Implement the method"],
        ),
    )


def report(
    code_artifact: CodeArtifact,
    *,
    run_id: int = 7,
    paper_id: int | None = None,
    origin: CodeArtifactOrigin | None = None,
    status: CodeArtifactStatus | None = None,
    check_status: ValidationCheckStatus = ValidationCheckStatus.PASSED,
) -> ValidationReport:
    validation_status = (
        ValidationStatus.FAILED
        if check_status is ValidationCheckStatus.FAILED
        else ValidationStatus.PARTIAL
    )
    return ValidationReport(
        literature_run_id=run_id,
        paper_id=paper_id or code_artifact.paper_id,
        artifact_origin=origin or code_artifact.origin,
        artifact_status=status or code_artifact.status,
        mode=ValidationMode.STATIC,
        status=validation_status,
        checks=[
            ValidationCheck(
                kind=ValidationCheckKind.REPRODUCTION_PLAN,
                status=check_status,
                summary="Reproduction plan checked",
            )
        ],
    )


def failure() -> WorkflowFailure:
    return WorkflowFailure(
        step=SupervisorStep.CODE,
        category=WorkflowFailureCategory.INTERNAL,
        message="Unexpected failure",
        error_type="RuntimeError",
    )


def state_for(status: WorkflowStatus) -> ModuleGraphState:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": status.value,
    }
    if status in {
        WorkflowStatus.PREPARING_CODE,
        WorkflowStatus.WAITING_FOR_CODE,
        WorkflowStatus.CODE_READY,
        WorkflowStatus.VALIDATING,
        WorkflowStatus.COMPLETED,
    }:
        state["selected_paper_ids"] = [1]

    code_artifact = artifact()
    if status in {
        WorkflowStatus.CODE_READY,
        WorkflowStatus.VALIDATING,
        WorkflowStatus.COMPLETED,
    }:
        state["code_artifacts"] = [
            code_artifact.model_dump(mode="json")
        ]

    if status is WorkflowStatus.COMPLETED:
        state["validation_reports"] = [
            report(code_artifact).model_dump(mode="json")
        ]

    if status is WorkflowStatus.FAILED:
        state["failure"] = failure().model_dump(mode="json")

    return state


@pytest.mark.parametrize("status", list(WorkflowStatus))
def test_validator_accepts_each_legal_workflow_status(
    status: WorkflowStatus,
) -> None:
    state = state_for(status)

    result = WorkflowStateValidator().validate(state)

    assert result is status


def test_validator_rejects_missing_status() -> None:
    with pytest.raises(ValueError, match="has no status"):
        WorkflowStateValidator().validate({"literature_run_id": 7})


@pytest.mark.parametrize("status", ["unknown", [], {}])
def test_validator_rejects_unknown_status(status: object) -> None:
    state = {
        "literature_run_id": 7,
        "status": status,
    }

    with pytest.raises(ValueError, match="Unknown workflow status"):
        WorkflowStateValidator().validate(state)  # type: ignore[arg-type]


def test_validator_reports_all_missing_required_fields() -> None:
    state: ModuleGraphState = {"status": WorkflowStatus.COMPLETED.value}

    with pytest.raises(ValueError) as exc_info:
        WorkflowStateValidator().validate(state)

    message = str(exc_info.value)
    assert "literature_run_id" in message
    assert "selected_paper_ids" in message
    assert "code_artifacts" in message
    assert "validation_reports" in message


@pytest.mark.parametrize("run_id", [0, -1, True, "7"])
def test_validator_rejects_invalid_literature_run_id(
    run_id: object,
) -> None:
    state: ModuleGraphState = {
        "literature_run_id": run_id,  # type: ignore[typeddict-item]
        "status": WorkflowStatus.CREATED.value,
    }

    with pytest.raises(ValueError, match="positive integer"):
        WorkflowStateValidator().validate(state)


@pytest.mark.parametrize(
    "paper_ids",
    [[0], [-1], [True], [1, 1], "1"],
)
def test_validator_rejects_invalid_selected_paper_ids(
    paper_ids: object,
) -> None:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.PREPARING_CODE.value,
        "selected_paper_ids": paper_ids,  # type: ignore[typeddict-item]
    }

    with pytest.raises(ValueError):
        WorkflowStateValidator().validate(state)


def test_code_artifacts_require_selection_even_in_failed_state() -> None:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.FAILED.value,
        "code_artifacts": [artifact().model_dump(mode="json")],
        "failure": failure().model_dump(mode="json"),
    }

    with pytest.raises(ValueError, match="require selected paper ids"):
        WorkflowStateValidator().validate(state)


def test_validation_reports_require_artifacts() -> None:
    code_artifact = artifact()
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.FAILED.value,
        "selected_paper_ids": [1],
        "validation_reports": [
            report(code_artifact).model_dump(mode="json")
        ],
        "failure": failure().model_dump(mode="json"),
    }

    with pytest.raises(ValueError, match="require code artifacts"):
        WorkflowStateValidator().validate(state)


def test_selection_cannot_appear_before_code_stage() -> None:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.WAITING_FOR_PAPER_SELECTION.value,
        "selected_paper_ids": [1],
    }

    with pytest.raises(ValueError, match="before the code stage"):
        WorkflowStateValidator().validate(state)


def test_artifacts_must_match_selected_papers() -> None:
    state = state_for(WorkflowStatus.CODE_READY)
    state["selected_paper_ids"] = [1, 2]

    with pytest.raises(ValueError, match="do not match selection"):
        WorkflowStateValidator().validate(state)


def test_reports_must_match_literature_run() -> None:
    state = state_for(WorkflowStatus.COMPLETED)
    code_artifact = artifact()
    state["validation_reports"] = [
        report(code_artifact, run_id=8).model_dump(mode="json")
    ]

    with pytest.raises(ValueError, match="does not match workflow"):
        WorkflowStateValidator().validate(state)


def test_reports_must_match_artifact_paper_ids() -> None:
    state = state_for(WorkflowStatus.COMPLETED)
    code_artifact = artifact()
    state["validation_reports"] = [
        report(code_artifact, paper_id=2).model_dump(mode="json")
    ]

    with pytest.raises(ValueError, match="do not match code artifacts"):
        WorkflowStateValidator().validate(state)


def test_report_metadata_must_match_artifact() -> None:
    state = state_for(WorkflowStatus.COMPLETED)
    code_artifact = artifact()
    state["validation_reports"] = [
        report(
            code_artifact,
            origin=CodeArtifactOrigin.UNKNOWN,
        ).model_dump(mode="json")
    ]

    with pytest.raises(ValueError, match="metadata does not match"):
        WorkflowStateValidator().validate(state)


def test_completed_workflow_accepts_failed_business_validation() -> None:
    state = state_for(WorkflowStatus.COMPLETED)
    code_artifact = artifact()
    state["validation_reports"] = [
        report(
            code_artifact,
            check_status=ValidationCheckStatus.FAILED,
        ).model_dump(mode="json")
    ]

    result = WorkflowStateValidator().validate(state)

    assert result is WorkflowStatus.COMPLETED


def test_failure_information_requires_failed_status() -> None:
    state = state_for(WorkflowStatus.CREATED)
    state["failure"] = failure().model_dump(mode="json")

    with pytest.raises(ValueError, match="requires failed status"):
        WorkflowStateValidator().validate(state)


def test_invalid_failure_payload_is_rejected() -> None:
    state = state_for(WorkflowStatus.FAILED)
    state["failure"] = {"category": "not-real"}

    with pytest.raises(ValueError, match="invalid failure information"):
        WorkflowStateValidator().validate(state)


def test_validator_accepts_recorded_attempt_counts() -> None:
    state = state_for(WorkflowStatus.VALIDATING)
    state["attempts"] = {
        SupervisorStep.LITERATURE.value: 1,
        SupervisorStep.VALIDATION.value: 2,
    }

    result = WorkflowStateValidator().validate(state)

    assert result is WorkflowStatus.VALIDATING


def test_none_failure_does_not_mark_workflow_as_failed() -> None:
    state = state_for(WorkflowStatus.VALIDATING)
    state["failure"] = None

    result = WorkflowStateValidator().validate(state)

    assert result is WorkflowStatus.VALIDATING


@pytest.mark.parametrize(
    ("attempts", "message"),
    [
        ([], "attempts must be a dictionary"),
        ({"unknown": 1}, "Unknown attempt step"),
        ({SupervisorStep.FINISH.value: 1}, "finish step"),
        ({SupervisorStep.VALIDATION.value: 0}, "positive integer"),
        ({SupervisorStep.VALIDATION.value: -1}, "positive integer"),
        ({SupervisorStep.VALIDATION.value: True}, "positive integer"),
        ({SupervisorStep.VALIDATION.value: 1.5}, "positive integer"),
    ],
)
def test_validator_rejects_invalid_attempt_counts(
    attempts: object,
    message: str,
) -> None:
    state = state_for(WorkflowStatus.VALIDATING)
    state["attempts"] = attempts  # type: ignore[typeddict-item]

    with pytest.raises(ValueError, match=message):
        WorkflowStateValidator().validate(state)
