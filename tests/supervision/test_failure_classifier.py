import pytest

from module_agent.supervision.application.failure_classifier import (
    WorkflowFailureClassifier,
)
from module_agent.supervision.domain import (
    WorkflowConfigurationError,
    WorkflowFailureCategory,
    WorkflowStateValidationError,
)
from module_agent.workflow.domain import SupervisorStep


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (
            WorkflowStateValidationError("Invalid checkpoint"),
            WorkflowFailureCategory.INVALID_STATE,
        ),
        (
            WorkflowConfigurationError("Missing configuration"),
            WorkflowFailureCategory.CONFIGURATION,
        ),
        (TimeoutError("Timed out"), WorkflowFailureCategory.TIMEOUT),
        (
            ConnectionError("Connection lost"),
            WorkflowFailureCategory.TRANSIENT_EXTERNAL,
        ),
        (RuntimeError("Unexpected"), WorkflowFailureCategory.INTERNAL),
    ],
)
def test_classifier_assigns_expected_category(
    exc: Exception,
    category: WorkflowFailureCategory,
) -> None:
    result = WorkflowFailureClassifier().classify(
        SupervisorStep.CODE,
        exc,
    )

    assert result.category is category
    assert result.message == str(exc)
    assert result.error_type == type(exc).__name__


@pytest.mark.parametrize(
    "step",
    [SupervisorStep.LITERATURE, SupervisorStep.VALIDATION],
)
@pytest.mark.parametrize(
    "exc",
    [TimeoutError("Timed out"), ConnectionError("Unavailable")],
)
def test_safe_transient_failure_is_retryable_within_budget(
    step: SupervisorStep,
    exc: Exception,
) -> None:
    result = WorkflowFailureClassifier(max_attempts=2).classify(
        step,
        exc,
        attempt=1,
    )

    assert result.retryable is True


@pytest.mark.parametrize(
    "exc",
    [TimeoutError("Timed out"), ConnectionError("Unavailable")],
)
def test_code_failure_is_not_retryable_by_default(exc: Exception) -> None:
    result = WorkflowFailureClassifier().classify(
        SupervisorStep.CODE,
        exc,
    )

    assert result.retryable is False


def test_retry_stops_when_attempt_budget_is_exhausted() -> None:
    result = WorkflowFailureClassifier(max_attempts=2).classify(
        SupervisorStep.LITERATURE,
        TimeoutError("Timed out"),
        attempt=2,
    )

    assert result.retryable is False
    assert result.attempt == 2


@pytest.mark.parametrize(
    "exc",
    [
        WorkflowStateValidationError("Invalid state"),
        WorkflowConfigurationError("Invalid configuration"),
        RuntimeError("Unexpected"),
    ],
)
def test_permanent_failures_are_not_retryable(exc: Exception) -> None:
    result = WorkflowFailureClassifier(max_attempts=5).classify(
        SupervisorStep.LITERATURE,
        exc,
    )

    assert result.retryable is False


def test_retryable_steps_can_be_configured_explicitly() -> None:
    classifier = WorkflowFailureClassifier(
        max_attempts=2,
        retryable_steps=[SupervisorStep.CODE],
    )

    result = classifier.classify(
        SupervisorStep.CODE,
        TimeoutError("Timed out"),
    )

    assert result.retryable is True


def test_finish_step_cannot_be_configured_for_retry() -> None:
    with pytest.raises(ValueError, match="finish step"):
        WorkflowFailureClassifier(
            retryable_steps=[SupervisorStep.FINISH]
        )


@pytest.mark.parametrize("max_attempts", [0, -1, True, 1.5])
def test_classifier_rejects_invalid_max_attempts(
    max_attempts: object,
) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        WorkflowFailureClassifier(max_attempts=max_attempts)  # type: ignore[arg-type]


@pytest.mark.parametrize("attempt", [0, -1, True, 1.5])
def test_classifier_rejects_invalid_attempt(attempt: object) -> None:
    with pytest.raises(ValueError, match="attempt"):
        WorkflowFailureClassifier().classify(
            SupervisorStep.LITERATURE,
            TimeoutError(),
            attempt=attempt,  # type: ignore[arg-type]
        )


def test_classifier_uses_exception_type_for_blank_message() -> None:
    result = WorkflowFailureClassifier().classify(
        SupervisorStep.CODE,
        RuntimeError(),
    )

    assert result.message == "RuntimeError"


def test_classifier_limits_stored_error_message() -> None:
    result = WorkflowFailureClassifier().classify(
        SupervisorStep.CODE,
        RuntimeError("x" * 2000),
    )

    assert len(result.message) == 1000
