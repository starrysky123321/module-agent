import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from module_agent.shared.exceptions import WorkflowControlError
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    ModuleWorkflowRunRepository,
    ModuleWorkflowRunStatus,
    WorkflowControlStatus,
)
from module_agent.workflow.lifecycle_service import (
    ModuleWorkflowLifecycleService,
)


def running_run(*, deadline_offset: int = 300) -> ModuleWorkflowRun:
    return ModuleWorkflowRun(
        literature_run_id=7,
        trace_id=uuid4(),
        status=ModuleWorkflowRunStatus.RUNNING,
        deadline_at=(
            datetime.now(timezone.utc)
            + timedelta(seconds=deadline_offset)
        ),
    )


def service_with_repository():
    repository = AsyncMock(spec=ModuleWorkflowRunRepository)

    async def save(run: ModuleWorkflowRun) -> ModuleWorkflowRun:
        return run

    repository.save.side_effect = save
    return (
        ModuleWorkflowLifecycleService(
            repository,
            default_timeout_seconds=3600,
        ),
        repository,
    )


def test_lifecycle_start_creates_stable_trace_and_deadline() -> None:
    service, repository = service_with_repository()
    repository.get.return_value = None
    before = datetime.now(timezone.utc)

    run = asyncio.run(service.start(7, timeout_seconds=120))

    assert run.status is ModuleWorkflowRunStatus.RUNNING
    assert run.deadline_at >= before + timedelta(seconds=119)
    repository.save.assert_awaited_once()


def test_lifecycle_start_is_idempotent() -> None:
    service, repository = service_with_repository()
    existing = running_run()
    repository.get.return_value = existing

    result = asyncio.run(service.start(7))

    assert result is existing
    repository.save.assert_not_awaited()


def test_cancel_is_idempotent_and_terminal() -> None:
    service, repository = service_with_repository()
    active = running_run()
    repository.get.return_value = active

    cancelled = asyncio.run(service.cancel(7))

    assert cancelled.status is ModuleWorkflowRunStatus.CANCELLED
    assert cancelled.cancellation_requested_at is not None
    assert cancelled.finished_at is not None

    repository.get.return_value = cancelled
    assert asyncio.run(service.cancel(7)) is cancelled


def test_completed_workflow_cannot_be_cancelled() -> None:
    service, repository = service_with_repository()
    now = datetime.now(timezone.utc)
    repository.get.return_value = ModuleWorkflowRun(
        literature_run_id=7,
        trace_id=uuid4(),
        status=ModuleWorkflowRunStatus.COMPLETED,
        deadline_at=now + timedelta(minutes=5),
        finished_at=now,
    )

    with pytest.raises(WorkflowControlError, match="cannot cancel"):
        asyncio.run(service.cancel(7))


def test_expired_deadline_is_persisted_as_timed_out() -> None:
    service, repository = service_with_repository()
    repository.get.return_value = running_run(deadline_offset=-1)

    status = asyncio.run(service.check_control(7))

    assert status is WorkflowControlStatus.TIMED_OUT
    saved = repository.save.await_args.args[0]
    assert saved.status is ModuleWorkflowRunStatus.TIMED_OUT
    assert saved.finished_at is not None
    assert saved.error == "Workflow deadline exceeded"


def test_timed_out_wait_can_be_resumed_with_new_deadline() -> None:
    service, repository = service_with_repository()
    now = datetime.now(timezone.utc)
    timed_out = ModuleWorkflowRun(
        literature_run_id=7,
        trace_id=uuid4(),
        status=ModuleWorkflowRunStatus.TIMED_OUT,
        deadline_at=now - timedelta(minutes=1),
        finished_at=now,
        error="Workflow deadline exceeded",
    )
    repository.get.return_value = timed_out

    resumed = asyncio.run(
        service.resume_timed_out(
            7,
            status=ModuleWorkflowRunStatus.WAITING_FOR_SELECTION,
            timeout_seconds=600,
        )
    )

    assert resumed.status is ModuleWorkflowRunStatus.WAITING_FOR_SELECTION
    assert resumed.finished_at is None
    assert resumed.error is None
    assert resumed.deadline_at > now + timedelta(minutes=9)


def test_active_workflow_cannot_use_timeout_resume() -> None:
    service, repository = service_with_repository()
    repository.get.return_value = running_run()

    with pytest.raises(WorkflowControlError, match="only a timed-out"):
        asyncio.run(
            service.resume_timed_out(
                7,
                status=ModuleWorkflowRunStatus.WAITING_FOR_SELECTION,
            )
        )
