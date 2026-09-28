import pytest
from pydantic import ValidationError

from module_agent.supervision.domain import (
    SupervisorAction,
    SupervisorDecision,
)
from module_agent.workflow.domain import (
    SupervisorStep,
    WorkflowStatus,
)


def test_decision_parses_enums_and_normalizes_reason() -> None:
    decision = SupervisorDecision(
        action="route",
        next_step="code",
        status="preparing_code",
        reason="  Selected papers are ready  ",
    )

    assert decision.action is SupervisorAction.ROUTE
    assert decision.next_step is SupervisorStep.CODE
    assert decision.status is WorkflowStatus.PREPARING_CODE
    assert decision.reason == "Selected papers are ready"


@pytest.mark.parametrize(
    ("action", "next_step", "status"),
    [
        (
            SupervisorAction.ROUTE,
            SupervisorStep.VALIDATION,
            WorkflowStatus.VALIDATING,
        ),
        (
            SupervisorAction.RETRY,
            SupervisorStep.CODE,
            WorkflowStatus.PREPARING_CODE,
        ),
        (
            SupervisorAction.FINISH,
            SupervisorStep.FINISH,
            WorkflowStatus.COMPLETED,
        ),
        (
            SupervisorAction.FAIL,
            SupervisorStep.FINISH,
            WorkflowStatus.FAILED,
        ),
        (
            SupervisorAction.WAIT,
            SupervisorStep.LITERATURE,
            WorkflowStatus.SEARCHING_LITERATURE,
        ),
        (
            SupervisorAction.WAIT,
            SupervisorStep.PAPER_SELECTION,
            WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
        ),
    ],
)
def test_decision_accepts_legal_combinations(
    action: SupervisorAction,
    next_step: SupervisorStep,
    status: WorkflowStatus,
) -> None:
    decision = SupervisorDecision(
        action=action,
        next_step=next_step,
        status=status,
        reason="Valid transition",
    )

    assert decision.action is action
    assert decision.next_step is next_step
    assert decision.status is status


@pytest.mark.parametrize(
    ("next_step", "status"),
    [
        (SupervisorStep.VALIDATION, WorkflowStatus.COMPLETED),
        (SupervisorStep.FINISH, WorkflowStatus.VALIDATING),
    ],
)
def test_finish_requires_finish_step_and_completed_status(
    next_step: SupervisorStep,
    status: WorkflowStatus,
) -> None:
    with pytest.raises(ValidationError, match="FINISH action requires"):
        SupervisorDecision(
            action=SupervisorAction.FINISH,
            next_step=next_step,
            status=status,
            reason="Invalid finish",
        )


@pytest.mark.parametrize(
    ("next_step", "status"),
    [
        (SupervisorStep.CODE, WorkflowStatus.FAILED),
        (SupervisorStep.FINISH, WorkflowStatus.COMPLETED),
    ],
)
def test_fail_requires_finish_step_and_failed_status(
    next_step: SupervisorStep,
    status: WorkflowStatus,
) -> None:
    with pytest.raises(ValidationError, match="FAIL action requires"):
        SupervisorDecision(
            action=SupervisorAction.FAIL,
            next_step=next_step,
            status=status,
            reason="Invalid failure",
        )


@pytest.mark.parametrize(
    "action",
    [SupervisorAction.ROUTE, SupervisorAction.RETRY],
)
def test_active_actions_cannot_target_finish(
    action: SupervisorAction,
) -> None:
    with pytest.raises(ValidationError, match="cannot target finish"):
        SupervisorDecision(
            action=action,
            next_step=SupervisorStep.FINISH,
            status=WorkflowStatus.PREPARING_CODE,
            reason="Invalid active action",
        )


@pytest.mark.parametrize(
    "status",
    [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED],
)
def test_route_cannot_use_terminal_status(status: WorkflowStatus) -> None:
    with pytest.raises(ValidationError, match="terminal status"):
        SupervisorDecision(
            action=SupervisorAction.ROUTE,
            next_step=SupervisorStep.CODE,
            status=status,
            reason="Invalid route",
        )


def test_wait_rejects_status_that_does_not_match_code_wait() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        SupervisorDecision(
            action=SupervisorAction.WAIT,
            next_step=SupervisorStep.CODE,
            status=WorkflowStatus.PREPARING_CODE,
            reason="Cannot wait for code",
        )


def test_wait_accepts_code_completion_step() -> None:
    decision = SupervisorDecision(
        action=SupervisorAction.WAIT,
        next_step=SupervisorStep.CODE,
        status=WorkflowStatus.WAITING_FOR_CODE,
        reason="Waiting for worker",
    )

    assert decision.action is SupervisorAction.WAIT


def test_wait_requires_status_matching_step() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        SupervisorDecision(
            action=SupervisorAction.WAIT,
            next_step=SupervisorStep.LITERATURE,
            status=WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
            reason="Mismatched wait",
        )


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
def test_decision_rejects_invalid_reason(reason: str) -> None:
    with pytest.raises(ValidationError):
        SupervisorDecision(
            action=SupervisorAction.ROUTE,
            next_step=SupervisorStep.CODE,
            status=WorkflowStatus.PREPARING_CODE,
            reason=reason,
        )
