import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.workflow.adapters.database.model import (
    ModuleWorkflowRunModel,
)
from module_agent.workflow.adapters.database.repository import (
    SqlAlchemyModuleWorkflowRunRepository,
)
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    ModuleWorkflowRunStatus,
)


def test_save_refreshes_server_generated_update_timestamp() -> None:
    now = datetime.now(timezone.utc)
    model = ModuleWorkflowRunModel(
        literature_run_id=7,
        trace_id=uuid4(),
        status=ModuleWorkflowRunStatus.RUNNING.value,
        deadline_at=now + timedelta(minutes=5),
        created_at=now,
        updated_at=now,
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = model
    repository = SqlAlchemyModuleWorkflowRunRepository(session)
    run = ModuleWorkflowRun(
        literature_run_id=7,
        trace_id=model.trace_id,
        status=ModuleWorkflowRunStatus.WAITING_FOR_LITERATURE,
        deadline_at=model.deadline_at,
        created_at=now,
        updated_at=now,
        selection_wait_started_at=None,
    )

    saved = asyncio.run(repository.save(run))

    assert saved.status is ModuleWorkflowRunStatus.WAITING_FOR_LITERATURE
    session.flush.assert_awaited_once_with()
    session.refresh.assert_awaited_once_with(model)


def test_selection_pause_timestamp_is_saved_and_loaded():
    now = datetime.now(timezone.utc)
    model = ModuleWorkflowRunModel(literature_run_id=7, trace_id=uuid4(), status="running", deadline_at=now + timedelta(minutes=5), created_at=now, updated_at=now)
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = model
    repository = SqlAlchemyModuleWorkflowRunRepository(session)
    paused = ModuleWorkflowRun(literature_run_id=7, trace_id=model.trace_id, status="waiting_for_selection", deadline_at=model.deadline_at, selection_wait_started_at=now)
    saved = asyncio.run(repository.save(paused))
    assert model.selection_wait_started_at == now
    assert saved.selection_wait_started_at == now
    assert asyncio.run(repository.get(7)).selection_wait_started_at == now
