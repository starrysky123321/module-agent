import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from typesafe_sdk import AsyncTypeSafeClient, ChoiceAnswer

from module_agent.supervision.adapters.jev_failure_advisor import (
    QUESTION_NAME,
    JevFailureAdvisor,
)
from module_agent.supervision.domain import (
    FailureDisposition,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import SupervisorStep


def failure(*, retryable: bool = True) -> WorkflowFailure:
    return WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=retryable,
        attempt=1,
        error_type="TimeoutError",
    )


def test_jev_failure_advisor_converts_choice_to_domain_advice() -> None:
    answer = ChoiceAnswer(
        choice="retry",
        confidence=0.91,
        probabilities={"retry": 0.91, "stop": 0.09},
    )
    response = MagicMock()
    response.choices = {QUESTION_NAME: answer}
    response.model = "jev-latest"
    response.request_id = "request-7"
    client = AsyncMock(spec=AsyncTypeSafeClient)
    client.system_one.return_value = response

    advice = asyncio.run(JevFailureAdvisor(client).advise(failure()))

    assert advice.disposition is FailureDisposition.RETRY
    assert advice.confidence == 0.91
    assert advice.probabilities == {
        FailureDisposition.RETRY: 0.91,
        FailureDisposition.STOP: 0.09,
    }
    assert advice.model == "jev-latest"
    assert advice.request_id == "request-7"
    assert advice.latency_ms >= 0


def test_jev_failure_advisor_sends_sanitized_failure_state() -> None:
    response = MagicMock()
    response.choices = {
        QUESTION_NAME: ChoiceAnswer(
            choice="stop",
            confidence=0.8,
            probabilities={"retry": 0.2, "stop": 0.8},
        )
    }
    response.model = "jev-latest"
    response.request_id = None
    client = AsyncMock(spec=AsyncTypeSafeClient)
    client.system_one.return_value = response

    asyncio.run(
        JevFailureAdvisor(client).advise(failure(retryable=True))
    )

    call = client.system_one.await_args
    state = call.kwargs["state"]
    question = call.kwargs["questions"][QUESTION_NAME]
    assert state == {
        "step": "validation",
        "category": "timeout",
        "message": "Validation timed out",
        "attempt": 1,
        "error_type": "TimeoutError",
    }
    assert "retryable" not in state
    assert set(question.criteria) == {"retry", "stop"}


def test_jev_failure_advisor_rejects_missing_answer() -> None:
    response = MagicMock()
    response.choices = {}
    client = AsyncMock(spec=AsyncTypeSafeClient)
    client.system_one.return_value = response

    with pytest.raises(RuntimeError, match="no failure disposition"):
        asyncio.run(JevFailureAdvisor(client).advise(failure()))
