import pytest
from pydantic import ValidationError

from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorFailureAdvice,
    SupervisorFailureObservation,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import SupervisorStep


def test_failure_advice_parses_serialized_choice_answer() -> None:
    advice = SupervisorFailureAdvice.model_validate(
        {
            "disposition": "retry",
            "confidence": 0.91,
            "probabilities": {
                "retry": 0.91,
                "stop": 0.09,
            },
            "model": "jev-latest",
            "request_id": "request-7",
            "latency_ms": 83,
        }
    )

    assert advice.disposition is FailureDisposition.RETRY
    assert advice.probabilities == {
        FailureDisposition.RETRY: 0.91,
        FailureDisposition.STOP: 0.09,
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_failure_advice_rejects_invalid_confidence(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        SupervisorFailureAdvice(
            disposition=FailureDisposition.STOP,
            confidence=confidence,
            probabilities={
                FailureDisposition.RETRY: 0.1,
                FailureDisposition.STOP: 0.9,
            },
            model="jev-latest",
            latency_ms=10,
        )


@pytest.mark.parametrize(
    "probabilities",
    [
        {FailureDisposition.RETRY: 1.0},
        {FailureDisposition.STOP: 1.0},
    ],
)
def test_failure_advice_requires_both_probability_options(
    probabilities: dict[FailureDisposition, float],
) -> None:
    with pytest.raises(ValidationError, match="retry and stop"):
        SupervisorFailureAdvice(
            disposition=FailureDisposition.RETRY,
            confidence=1.0,
            probabilities=probabilities,
            model="jev-latest",
            latency_ms=10,
        )


def test_failure_advice_rejects_negative_latency() -> None:
    with pytest.raises(ValidationError):
        SupervisorFailureAdvice(
            disposition=FailureDisposition.STOP,
            confidence=0.8,
            probabilities={
                FailureDisposition.RETRY: 0.2,
                FailureDisposition.STOP: 0.8,
            },
            model="jev-latest",
            latency_ms=-1,
        )


def test_failure_observation_accepts_successful_comparison() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=True,
    )
    advice = SupervisorFailureAdvice(
        disposition=FailureDisposition.RETRY,
        confidence=0.9,
        probabilities={
            FailureDisposition.RETRY: 0.9,
            FailureDisposition.STOP: 0.1,
        },
        model="jev-latest",
        latency_ms=20,
    )

    observation = SupervisorFailureObservation(
        literature_run_id=7,
        failure=failure,
        rule_disposition=FailureDisposition.RETRY,
        advice=advice,
        agrees=True,
        meets_confidence_threshold=True,
    )

    assert observation.error is None


def test_failure_observation_accepts_advisor_error() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=True,
    )

    observation = SupervisorFailureObservation(
        literature_run_id=7,
        failure=failure,
        rule_disposition=FailureDisposition.RETRY,
        error="Jev unavailable",
    )

    assert observation.advice is None


def test_failure_observation_rejects_incomplete_success() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=True,
    )
    advice = SupervisorFailureAdvice(
        disposition=FailureDisposition.RETRY,
        confidence=0.9,
        probabilities={
            FailureDisposition.RETRY: 0.9,
            FailureDisposition.STOP: 0.1,
        },
        model="jev-latest",
        latency_ms=20,
    )

    with pytest.raises(ValidationError, match="comparison fields"):
        SupervisorFailureObservation(
            literature_run_id=7,
            failure=failure,
            rule_disposition=FailureDisposition.RETRY,
            advice=advice,
        )
