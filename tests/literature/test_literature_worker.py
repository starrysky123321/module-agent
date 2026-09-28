import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.domain.jobs import (
    LiteratureJob,
    LiteratureJobConsumer,
)
from module_agent.literature.domain.events import (
    LiteratureCompletionPublisher,
)
from module_agent.literature.application.execution import LiteratureRunExecutor
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.literature.workers.search import LiteratureWorker


def worker_dependencies(
    executor: AsyncMock,
) -> tuple[
    AsyncMock,
    AsyncMock,
    MagicMock,
    MagicMock,
    list[MagicMock],
    list[MagicMock],
]:
    consumer = AsyncMock(spec=LiteratureJobConsumer)
    sessions: list[MagicMock] = []
    transactions: list[MagicMock] = []
    session_contexts: list[MagicMock] = []
    for _ in range(2):
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock(spec=AsyncSession)
        session.begin.return_value = transaction
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=None)
        transactions.append(transaction)
        sessions.append(session)
        session_contexts.append(session_context)

    session_factory = MagicMock(side_effect=session_contexts)
    executor_factory = MagicMock(return_value=executor)
    publisher = AsyncMock(spec=LiteratureCompletionPublisher)
    return (
        consumer,
        publisher,
        session_factory,
        executor_factory,
        sessions,
        transactions,
    )


def test_worker_registers_its_handler_with_consumer() -> None:
    executor = AsyncMock(spec=LiteratureRunExecutor)
    consumer, publisher, session_factory, executor_factory, _, _ = worker_dependencies(
        executor
    )
    worker = LiteratureWorker(
        consumer, publisher, session_factory, executor_factory
    )

    asyncio.run(worker.run())

    consumer.run.assert_awaited_once_with(worker._handle)


def test_worker_executes_job_in_fresh_transaction() -> None:
    executor = AsyncMock(spec=LiteratureRunExecutor)
    started_run = object()
    executor.start.return_value = started_run
    consumer, publisher, session_factory, executor_factory, sessions, transactions = (
        worker_dependencies(executor)
    )
    worker = LiteratureWorker(
        consumer, publisher, session_factory, executor_factory
    )

    async def assert_committed_before_publish(_: int) -> str:
        assert transactions[1].__aexit__.await_count == 1
        return "completion-message"

    publisher.publish.side_effect = assert_committed_before_publish

    asyncio.run(
        worker._handle(
            LiteratureJob(run_id=8, resume_workflow=True)
        )
    )

    assert session_factory.call_count == 2
    assert executor_factory.call_args_list == [
        ((sessions[0],), {}),
        ((sessions[1],), {}),
    ]
    executor.get_run.assert_awaited_once_with(8)
    executor.start.assert_awaited_once_with(8)
    executor.execute_started.assert_awaited_once_with(started_run)
    publisher.publish.assert_awaited_once_with(8)
    transactions[0].__aexit__.assert_awaited_once_with(None, None, None)
    transactions[1].__aexit__.assert_awaited_once_with(None, None, None)


def test_worker_propagates_executor_failure_for_consumer_to_nack() -> None:
    error = RuntimeError("execution failed")
    executor = AsyncMock(spec=LiteratureRunExecutor)
    executor.start.return_value = object()
    executor.execute_started.side_effect = error
    consumer, publisher, session_factory, executor_factory, _, transactions = (
        worker_dependencies(executor)
    )
    worker = LiteratureWorker(
        consumer, publisher, session_factory, executor_factory
    )

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(
            worker._handle(
                LiteratureJob(run_id=8, resume_workflow=True)
            )
        )

    assert captured.value is error
    transactions[0].__aexit__.assert_awaited_once_with(None, None, None)
    exit_args = transactions[1].__aexit__.await_args.args
    assert exit_args[0] is RuntimeError
    assert exit_args[1] is error
    publisher.publish.assert_not_awaited()


def test_worker_republishes_completion_without_reexecuting_completed_run() -> None:
    executor = AsyncMock(spec=LiteratureRunExecutor)
    executor.get_run.return_value = SimpleNamespace(
        status=LiteratureRunStatus.COMPLETED
    )
    consumer, publisher, session_factory, executor_factory, _, transactions = (
        worker_dependencies(executor)
    )
    worker = LiteratureWorker(
        consumer, publisher, session_factory, executor_factory
    )

    asyncio.run(
        worker._handle(
            LiteratureJob(run_id=8, resume_workflow=True)
        )
    )

    assert session_factory.call_count == 1
    transactions[0].__aexit__.assert_awaited_once_with(None, None, None)
    executor.start.assert_not_awaited()
    executor.execute_started.assert_not_awaited()
    publisher.publish.assert_awaited_once_with(8)


def test_worker_does_not_publish_completion_for_standalone_job() -> None:
    executor = AsyncMock(spec=LiteratureRunExecutor)
    executor.start.return_value = object()
    consumer, publisher, session_factory, executor_factory, _, _ = (
        worker_dependencies(executor)
    )
    worker = LiteratureWorker(
        consumer, publisher, session_factory, executor_factory
    )

    asyncio.run(worker._handle(LiteratureJob(run_id=8)))

    executor.execute_started.assert_awaited_once()
    publisher.publish.assert_not_awaited()
