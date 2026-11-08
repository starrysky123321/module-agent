"""Pause clocks survive fresh database sessions, without running any agents."""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from module_agent.bootstrap import database_models  # noqa: F401
from module_agent.literature.adapters.database.models.run import LiteratureRunModel
from module_agent.shared.config import app_settings
from module_agent.shared.database.session import create_database_engine
from module_agent.workflow.adapters.database.model import ModuleWorkflowRunModel
from module_agent.workflow.adapters.database.repository import TransactionalModuleWorkflowRunRepository
from module_agent.workflow.lifecycle import ModuleWorkflowRunStatus, WorkflowControlStatus
from module_agent.workflow.lifecycle_service import ModuleWorkflowLifecycleService


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 to test PostgreSQL pause clocks",
)


def test_selection_wait_persists_and_preserves_only_remaining_execution_budget():
    async def verify():
        engine = create_database_engine(app_settings.database_url)
        try:
            async with engine.connect() as connection:
                outer = await connection.begin()
                factory = async_sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
                try:
                    pause = datetime.now(timezone.utc) - timedelta(days=3)
                    async with factory() as session, session.begin():
                        task = LiteratureRunModel(status="completed", request={})
                        session.add(task)
                        await session.flush()
                        run_id = task.id
                        session.add(ModuleWorkflowRunModel(
                            literature_run_id=run_id, trace_id=uuid4(), status="waiting_for_selection",
                            deadline_at=pause + timedelta(minutes=15), selection_wait_started_at=pause,
                        ))
                    repository = TransactionalModuleWorkflowRunRepository(factory)
                    service = ModuleWorkflowLifecycleService(repository, default_timeout_seconds=3600)
                    assert await service.check_control(run_id) is WorkflowControlStatus.ACTIVE
                    # A new repository/service instance reads no in-memory clock.
                    restarted = ModuleWorkflowLifecycleService(TransactionalModuleWorkflowRunRepository(factory), default_timeout_seconds=3600)
                    saved = await restarted.get(run_id)
                    assert saved.selection_wait_started_at == pause
                    resumed = await restarted.set_status(run_id, ModuleWorkflowRunStatus.RUNNING)
                    remaining = (resumed.deadline_at - datetime.now(timezone.utc)).total_seconds()
                    assert 899 < remaining <= 900
                    assert resumed.selection_wait_started_at is None
                    async with factory() as session, session.begin():
                        row = await session.get(ModuleWorkflowRunModel, run_id)
                        row.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                    assert await restarted.check_control(run_id) is WorkflowControlStatus.TIMED_OUT
                finally:
                    await outer.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())
