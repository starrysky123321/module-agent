import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from module_agent.code.domain.events import (
    CodeCompletedEvent,
    CodeCompletionConsumer,
)
from module_agent.code.workers.completion import CodeCompletionWorker
from module_agent.workflow.service import ModuleWorkflowService


def _worker() -> tuple[CodeCompletionWorker, AsyncMock, AsyncMock]:
    consumer = AsyncMock(spec=CodeCompletionConsumer)
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    return (
        CodeCompletionWorker(
            consumer=consumer,
            workflow_service=workflow_service,
        ),
        consumer,
        workflow_service,
    )


def _event() -> CodeCompletedEvent:
    return CodeCompletedEvent(
        literature_run_id=7,
        code_run_id=3,
        trace_id=uuid4(),
    )


def test_completion_worker_registers_handler() -> None:
    worker, consumer, _ = _worker()

    asyncio.run(worker.run())

    consumer.run.assert_awaited_once_with(worker._handle)


def test_completion_worker_resumes_workflow() -> None:
    worker, _, workflow_service = _worker()
    event = _event()

    asyncio.run(worker._handle(event))

    workflow_service.resume_code_workflow.assert_awaited_once_with(7, 3)


def test_completion_worker_propagates_resume_failure() -> None:
    worker, _, workflow_service = _worker()
    error = RuntimeError("checkpoint unavailable")
    workflow_service.resume_code_workflow.side_effect = error

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(worker._handle(_event()))

    assert captured.value is error
