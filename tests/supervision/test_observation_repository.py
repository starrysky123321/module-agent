import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.supervision.adapters.database.models.observation import (
    SupervisorFailureObservationModel,
)
from module_agent.supervision.adapters.database.observation_sink import (
    SqlAlchemySupervisorObservationSink,
)
from module_agent.supervision.adapters.database import observation_sink
from module_agent.supervision.adapters.database.repositories.observation import (
    SqlAlchemySupervisorObservationRepository,
)
from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorFailureAdvice,
    SupervisorFailureObservation,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import SupervisorStep


def successful_observation() -> SupervisorFailureObservation:
    return SupervisorFailureObservation(
        literature_run_id=42,
        failure=WorkflowFailure(
            step=SupervisorStep.VALIDATION,
            category=WorkflowFailureCategory.TIMEOUT,
            message="Validation timed out",
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
            model="jev-1.13.0",
            request_id="req-42",
            latency_ms=321,
        ),
        agrees=False,
        meets_confidence_threshold=True,
    )


def test_repository_maps_successful_observation_without_commit() -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemySupervisorObservationRepository(session)

    asyncio.run(repository.add(successful_observation()))

    model = session.add.call_args.args[0]
    assert isinstance(model, SupervisorFailureObservationModel)
    assert model.literature_run_id == 42
    assert model.failure_step == "validation"
    assert model.failure_category == "timeout"
    assert model.failure_retryable is True
    assert model.failure_attempt == 2
    assert model.rule_disposition == "retry"
    assert model.jev_disposition == "stop"
    assert model.confidence == 0.9
    assert model.retry_probability == 0.1
    assert model.stop_probability == 0.9
    assert model.agrees is False
    assert model.meets_confidence_threshold is True
    assert model.error is None
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


def test_repository_maps_failed_jev_call() -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemySupervisorObservationRepository(session)
    observation = SupervisorFailureObservation(
        literature_run_id=7,
        failure=WorkflowFailure(
            step=SupervisorStep.CODE,
            category=WorkflowFailureCategory.TRANSIENT_EXTERNAL,
            message="Jev unavailable",
            retryable=True,
        ),
        rule_disposition=FailureDisposition.RETRY,
        error="Jev timed out",
    )

    asyncio.run(repository.add(observation))

    model = session.add.call_args.args[0]
    assert model.jev_disposition is None
    assert model.confidence is None
    assert model.retry_probability is None
    assert model.stop_probability is None
    assert model.agrees is None
    assert model.error == "Jev timed out"


def test_sink_uses_its_own_transaction() -> None:
    session = AsyncMock(spec=AsyncSession)
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=None)
    session.begin.return_value = transaction

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session_context)
    sink = SqlAlchemySupervisorObservationSink(session_factory)

    asyncio.run(sink.record(successful_observation()))

    session_factory.assert_called_once_with()
    session.begin.assert_called_once_with()
    session.add.assert_called_once()
    session.flush.assert_awaited_once_with()
    transaction.__aexit__.assert_awaited_once()
    session_context.__aexit__.assert_awaited_once()


def test_sink_logs_and_reraises_persistence_failure(
    monkeypatch,
) -> None:
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(
        side_effect=RuntimeError("database unavailable")
    )
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session_context)
    logger = MagicMock()
    monkeypatch.setattr(observation_sink, "logger", logger)
    sink = SqlAlchemySupervisorObservationSink(session_factory)

    try:
        asyncio.run(sink.record(successful_observation()))
    except RuntimeError as exc:
        assert str(exc) == "database unavailable"
    else:
        raise AssertionError("Expected persistence error")

    logger.exception.assert_called_once_with(
        "supervisor observation persistence failed | run_id={}",
        42,
    )
