import pytest
from pydantic import ValidationError

from module_agent.supervision.domain import (
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import SupervisorStep


def test_failure_parses_enums_normalizes_text_and_uses_defaults() -> None:
    failure = WorkflowFailure(
        step="code",
        category="internal",
        message="  Unexpected code failure  ",
    )

    assert failure.step is SupervisorStep.CODE
    assert failure.category is WorkflowFailureCategory.INTERNAL
    assert failure.message == "Unexpected code failure"
    assert failure.retryable is False
    assert failure.attempt == 1
    assert failure.error_type is None


def test_transient_failure_can_be_retryable() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.LITERATURE,
        category=WorkflowFailureCategory.TRANSIENT_EXTERNAL,
        message="Source temporarily unavailable",
        retryable=True,
        attempt=2,
        error_type="  UpstreamUnavailableError  ",
    )

    assert failure.retryable is True
    assert failure.attempt == 2
    assert failure.error_type == "UpstreamUnavailableError"


@pytest.mark.parametrize(
    "category",
    [
        WorkflowFailureCategory.CONFIGURATION,
        WorkflowFailureCategory.INVALID_STATE,
    ],
)
def test_non_retryable_categories_reject_retry_flag(
    category: WorkflowFailureCategory,
) -> None:
    with pytest.raises(ValidationError, match="cannot be retried"):
        WorkflowFailure(
            step=SupervisorStep.CODE,
            category=category,
            message="Permanent failure",
            retryable=True,
        )


@pytest.mark.parametrize("attempt", [0, -1])
def test_failure_rejects_non_positive_attempt(attempt: int) -> None:
    with pytest.raises(ValidationError):
        WorkflowFailure(
            step=SupervisorStep.CODE,
            category=WorkflowFailureCategory.INTERNAL,
            message="Failure",
            attempt=attempt,
        )


@pytest.mark.parametrize("message", ["", "   ", "x" * 1001])
def test_failure_rejects_invalid_message(message: str) -> None:
    with pytest.raises(ValidationError):
        WorkflowFailure(
            step=SupervisorStep.CODE,
            category=WorkflowFailureCategory.INTERNAL,
            message=message,
        )


@pytest.mark.parametrize("error_type", ["", "   ", "x" * 201])
def test_failure_rejects_invalid_error_type(error_type: str) -> None:
    with pytest.raises(ValidationError):
        WorkflowFailure(
            step=SupervisorStep.CODE,
            category=WorkflowFailureCategory.INTERNAL,
            message="Failure",
            error_type=error_type,
        )
