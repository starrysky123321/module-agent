import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from module_agent.code.application.recovery import CodeRunRecoveryService
from module_agent.code.domain import CodeAgentRequest, CodePaperInput
from module_agent.code.domain.events import CodeCompletionPublisher
from module_agent.code.domain.jobs import CodeJob, CodeJobConsumer
from module_agent.code.workers.dead_letter import CodeDeadWorker


def _job() -> CodeJob:
    return CodeJob(
        request=CodeAgentRequest(
            literature_run_id=7,
            papers=[
                CodePaperInput(
                    paper_id=51,
                    source="openalex",
                    source_id="W51",
                    title="Paper 51",
                )
            ],
        ),
        attempt=1,
        trace_id=uuid4(),
    )


def _worker() -> tuple[CodeDeadWorker, AsyncMock, AsyncMock, AsyncMock]:
    consumer = AsyncMock(spec=CodeJobConsumer)
    recovery = AsyncMock(spec=CodeRunRecoveryService)
    publisher = AsyncMock(spec=CodeCompletionPublisher)
    worker = CodeDeadWorker(
        consumer=consumer,
        recovery_service=recovery,
        completion_publisher=publisher,
    )
    return worker, consumer, recovery, publisher


def test_dead_worker_registers_handler() -> None:
    worker, consumer, _, _ = _worker()

    asyncio.run(worker.run())

    consumer.run.assert_awaited_once_with(worker._handle)


def test_dead_worker_marks_failed_and_publishes_completion() -> None:
    worker, _, recovery, publisher = _worker()
    job = _job()
    recovery.fail_exhausted_execution.return_value.id = 4

    asyncio.run(worker._handle(job))

    recovery.fail_exhausted_execution.assert_awaited_once_with(
        job.request,
        attempt=job.attempt,
        trace_id=job.trace_id,
        error="Code job exceeded RabbitMQ delivery limit",
    )
    event = publisher.publish.await_args.args[0]
    assert event.literature_run_id == 7
    assert event.code_run_id == 4
    assert event.trace_id == job.trace_id


def test_dead_worker_propagates_recovery_failure() -> None:
    worker, _, recovery, publisher = _worker()
    job = _job()
    error = RuntimeError("database unavailable")
    recovery.fail_exhausted_execution.side_effect = error

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(worker._handle(job))

    assert captured.value is error
    publisher.publish.assert_not_awaited()
