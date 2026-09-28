import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.domain.jobs import (
    LiteratureJob,
    LiteratureJobConsumer,
)
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.workers.dead_letter import LiteratureDeadWorker


def worker_dependencies(
    run_service: AsyncMock,
) -> tuple[AsyncMock, MagicMock, MagicMock, MagicMock]:
    consumer = AsyncMock(spec=LiteratureJobConsumer)
    transaction_context = MagicMock()
    transaction_context.__aenter__ = AsyncMock(return_value=None)
    transaction_context.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock(spec=AsyncSession)
    session.begin.return_value = transaction_context
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session_context)
    run_service_factory = MagicMock(return_value=run_service)
    return consumer, session_factory, run_service_factory, transaction_context


def test_dead_worker_registers_its_handler_with_consumer() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    consumer, session_factory, run_service_factory, _ = worker_dependencies(
        run_service
    )
    worker = LiteratureDeadWorker(
        consumer,
        session_factory,
        run_service_factory,
    )

    asyncio.run(worker.run())

    consumer.run.assert_awaited_once_with(worker._handle)


def test_dead_worker_marks_exhausted_run_failed_in_fresh_transaction() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    consumer, session_factory, run_service_factory, transaction = (
        worker_dependencies(run_service)
    )
    worker = LiteratureDeadWorker(
        consumer,
        session_factory,
        run_service_factory,
    )

    asyncio.run(worker._handle(LiteratureJob(run_id=8)))

    session_factory.assert_called_once_with()
    session = session_factory.return_value.__aenter__.return_value
    run_service_factory.assert_called_once_with(session)
    run_service.fail_exhausted_run.assert_awaited_once_with(
        8,
        "Literature job exceeded retry limit",
    )
    transaction.__aexit__.assert_awaited_once_with(None, None, None)


def test_dead_worker_propagates_failure_for_consumer_to_requeue() -> None:
    error = RuntimeError("database unavailable")
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.fail_exhausted_run.side_effect = error
    consumer, session_factory, run_service_factory, transaction = (
        worker_dependencies(run_service)
    )
    worker = LiteratureDeadWorker(
        consumer,
        session_factory,
        run_service_factory,
    )

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(worker._handle(LiteratureJob(run_id=8)))

    assert captured.value is error
    exit_args = transaction.__aexit__.await_args.args
    assert exit_args[0] is RuntimeError
    assert exit_args[1] is error
