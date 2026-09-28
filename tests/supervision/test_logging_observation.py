import asyncio
from unittest.mock import MagicMock

from module_agent.supervision.adapters import logging_observation
from module_agent.supervision.adapters.logging_observation import (
    LoggingSupervisorObservationSink,
)
from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorFailureAdvice,
    SupervisorFailureObservation,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import SupervisorStep


def test_logging_sink_writes_structured_observation(
    monkeypatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(logging_observation, "logger", logger)
    observation = SupervisorFailureObservation(
        literature_run_id=12,
        failure=WorkflowFailure(
            step=SupervisorStep.CODE,
            category=WorkflowFailureCategory.TIMEOUT,
            message="Repository lookup timed out",
            retryable=True,
            attempt=2,
            error_type="TimeoutError",
        ),
        rule_disposition=FailureDisposition.RETRY,
        advice=SupervisorFailureAdvice(
            disposition=FailureDisposition.STOP,
            confidence=0.9,
            probabilities={
                FailureDisposition.RETRY: 0.1,
                FailureDisposition.STOP: 0.9,
            },
            model="jev-latest",
            request_id="req-1",
            latency_ms=25,
        ),
        agrees=False,
        meets_confidence_threshold=True,
    )

    asyncio.run(LoggingSupervisorObservationSink().record(observation))

    logger.info.assert_called_once_with(
        "supervisor_failure_shadow_observation | {}",
        observation.model_dump(mode="json"),
    )
