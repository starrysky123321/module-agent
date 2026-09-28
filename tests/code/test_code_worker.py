import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from module_agent.code.application.run import CodeRunService
from module_agent.code.domain import (
    CodeAgentRequest,
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    CodePaperInput,
    CodeRun,
    CodeRunRepository,
    CodeRunStatus,
    ReproductionPlan,
)
from module_agent.code.domain.events import CodeCompletionPublisher
from module_agent.code.domain.jobs import (
    CodeJob,
    CodeJobConsumer,
    ComputeTarget,
)
from module_agent.code.workers.code import CodeWorker


def _request() -> CodeAgentRequest:
    return CodeAgentRequest(
        literature_run_id=7,
        papers=[
            CodePaperInput(
                paper_id=51,
                source="openalex",
                source_id="W51",
                title="Paper 51",
            )
        ],
    )


def _artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=51,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Test problem",
            implementation_steps=["Implement method"],
        ),
    )


def _job() -> CodeJob:
    return CodeJob(
        request=_request(),
        attempt=1,
        trace_id=uuid4(),
        compute_target=ComputeTarget.CPU,
    )


def _run(job: CodeJob, status: CodeRunStatus) -> CodeRun:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "id": 3,
        "literature_run_id": job.request.literature_run_id,
        "attempt": job.attempt,
        "trace_id": job.trace_id,
        "status": status,
        "request": job.request,
        "started_at": now,
    }
    if status is CodeRunStatus.COMPLETED:
        values.update(artifacts=[_artifact()], finished_at=now)
    elif status is CodeRunStatus.FAILED:
        values.update(error="execution failed", finished_at=now)
    return CodeRun.model_validate(values)


def _worker() -> tuple[
    CodeWorker,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    consumer = AsyncMock(spec=CodeJobConsumer)
    repository = AsyncMock(spec=CodeRunRepository)
    run_service = AsyncMock(spec=CodeRunService)
    run_service.repository = repository
    publisher = AsyncMock(spec=CodeCompletionPublisher)
    worker = CodeWorker(
        consumer=consumer,
        run_service=run_service,
        completion_publisher=publisher,
    )
    return worker, run_service, repository, publisher


def test_worker_registers_handler_with_consumer() -> None:
    worker, _, _, _ = _worker()

    asyncio.run(worker.run())

    worker.consumer.run.assert_awaited_once_with(worker._handle)


def test_worker_publishes_completion_for_completed_run() -> None:
    worker, run_service, _, publisher = _worker()
    job = _job()
    completed = _run(job, CodeRunStatus.COMPLETED)
    run_service.execute.return_value = completed

    asyncio.run(worker._handle(job))

    run_service.execute.assert_awaited_once_with(
        job.request,
        attempt=job.attempt,
        trace_id=job.trace_id,
    )
    event = publisher.publish.await_args.args[0]
    assert event.literature_run_id == job.request.literature_run_id
    assert event.code_run_id == completed.id
    assert event.trace_id == job.trace_id


def test_worker_publishes_completion_for_persisted_failure() -> None:
    worker, run_service, repository, publisher = _worker()
    job = _job()
    error = RuntimeError("execution failed")
    failed = _run(job, CodeRunStatus.FAILED)
    run_service.execute.side_effect = error
    repository.get_by_execution.return_value = failed

    asyncio.run(worker._handle(job))

    repository.get_by_execution.assert_awaited_once_with(
        job.request.literature_run_id,
        job.attempt,
    )
    event = publisher.publish.await_args.args[0]
    assert event.code_run_id == failed.id


def test_worker_propagates_failure_while_run_is_still_running() -> None:
    worker, run_service, repository, publisher = _worker()
    job = _job()
    error = RuntimeError("execution interrupted")
    run_service.execute.side_effect = error
    repository.get_by_execution.return_value = _run(
        job,
        CodeRunStatus.RUNNING,
    )

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(worker._handle(job))

    assert captured.value is error
    publisher.publish.assert_not_awaited()


def test_worker_propagates_failure_without_persisted_run() -> None:
    worker, run_service, repository, publisher = _worker()
    job = _job()
    error = RuntimeError("database unavailable")
    run_service.execute.side_effect = error
    repository.get_by_execution.return_value = None

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(worker._handle(job))

    assert captured.value is error
    publisher.publish.assert_not_awaited()
