import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.domain.events import (
    LiteratureCompletedEvent,
    LiteratureCompletionConsumer,
)
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)
from module_agent.literature.workers.completion import (
    LiteratureCompletionWorker,
)


def _dependencies() -> tuple[
    AsyncMock,
    MagicMock,
    MagicMock,
    MagicMock,
    AsyncMock,
]:
    consumer = AsyncMock(spec=LiteratureCompletionConsumer)
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock(spec=AsyncSession)
    session.begin.return_value = transaction
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session_context)
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator_factory = MagicMock(return_value=coordinator)
    return (
        consumer,
        session_factory,
        coordinator_factory,
        session,
        coordinator,
    )


def test_completion_worker_registers_handler() -> None:
    consumer, session_factory, coordinator_factory, _, _ = _dependencies()
    worker = LiteratureCompletionWorker(
        consumer,
        session_factory,
        coordinator_factory,
    )

    asyncio.run(worker.run())

    consumer.run.assert_awaited_once_with(worker._handle)


def test_completion_worker_resumes_workflow_in_transaction() -> None:
    consumer, session_factory, coordinator_factory, session, coordinator = (
        _dependencies()
    )
    worker = LiteratureCompletionWorker(
        consumer,
        session_factory,
        coordinator_factory,
    )

    asyncio.run(worker._handle(LiteratureCompletedEvent(run_id=8)))

    coordinator_factory.assert_called_once_with(session)
    coordinator.resume_after_literature_completion.assert_awaited_once_with(8)


def test_completion_worker_propagates_resume_failure() -> None:
    consumer, session_factory, coordinator_factory, _, coordinator = (
        _dependencies()
    )
    error = RuntimeError("checkpoint unavailable")
    coordinator.resume_after_literature_completion.side_effect = error
    worker = LiteratureCompletionWorker(
        consumer,
        session_factory,
        coordinator_factory,
    )

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(worker._handle(LiteratureCompletedEvent(run_id=8)))

    assert captured.value is error
