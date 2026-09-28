import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.run import LiteratureRun, LiteratureRunStatus
from module_agent.literature.domain.jobs import LiteratureJobQueue
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.literature.application.run import LiteratureRunService


def queued_run(run_id: int | None) -> LiteratureRun:
    return LiteratureRun(
        id=run_id,
        status=LiteratureRunStatus.QUEUED,
        request=SearchRequest(
            topic="graph neural networks",
            description="Find representative papers",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            keywords=["GNN"],
            max_results=10,
        ),
    )


def test_dispatcher_queues_run_and_publishes_job() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.queue_run.return_value = queued_run(7)
    job_queue = AsyncMock(spec=LiteratureJobQueue)
    job_queue.enqueue.return_value = "message-123"
    dispatcher = LiteratureRunDispatcher(run_service, job_queue)

    message_id = asyncio.run(dispatcher.dispatch(7))

    assert message_id == "message-123"
    run_service.queue_run.assert_awaited_once_with(7)
    job_queue.enqueue.assert_awaited_once_with(
        7,
        resume_workflow=False,
    )


def test_dispatcher_rejects_queued_run_without_id() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.queue_run.return_value = queued_run(None)
    job_queue = AsyncMock(spec=LiteratureJobQueue)
    dispatcher = LiteratureRunDispatcher(run_service, job_queue)

    with pytest.raises(RuntimeError, match="missing id"):
        asyncio.run(dispatcher.dispatch(7))

    job_queue.enqueue.assert_not_awaited()


def test_dispatcher_marks_job_for_workflow_resume() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.queue_run.return_value = queued_run(7)
    job_queue = AsyncMock(spec=LiteratureJobQueue)
    job_queue.enqueue.return_value = "message-123"
    dispatcher = LiteratureRunDispatcher(run_service, job_queue)

    asyncio.run(dispatcher.dispatch(7, resume_workflow=True))

    job_queue.enqueue.assert_awaited_once_with(
        7,
        resume_workflow=True,
    )


def test_dispatcher_propagates_publish_failure() -> None:
    publish_error = RuntimeError("RabbitMQ unavailable")
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.queue_run.return_value = queued_run(7)
    job_queue = AsyncMock(spec=LiteratureJobQueue)
    job_queue.enqueue.side_effect = publish_error
    dispatcher = LiteratureRunDispatcher(run_service, job_queue)

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(dispatcher.dispatch(7))

    assert captured.value is publish_error
