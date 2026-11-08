"""Verify real cascades/checkpoint removal using rollback-only fixture rows."""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from module_agent.bootstrap import database_models  # noqa: F401
from module_agent.api.exception_handlers import register_exception_handlers
from module_agent.bootstrap.api_dependencies import get_task_deletion_service
from module_agent.literature.api.router import literature_router
from module_agent.literature.adapters.database.models.run import LiteratureRunModel, LiteratureRunPaperModel
from module_agent.literature.adapters.database.models.paper import PaperModel
from module_agent.literature.adapters.database.models.selection import PaperSelectionModel
from module_agent.code.adapters.database.models.run import CodeRunModel, CodeRunArtifactModel
from module_agent.validation.adapters.database.models.run import ValidationRunModel, ValidationRunReportModel
from module_agent.workflow.adapters.database.model import ModuleWorkflowRunModel
from module_agent.workflow.adapters.database.node_execution_model import WorkflowNodeExecutionModel
from module_agent.workflow.adapters.database.deletion import SqlAlchemyTaskDeletionRepository
from module_agent.workflow.deletion import TaskDeletionService
from module_agent.shared.config import app_settings
from module_agent.shared.database.session import create_database_engine


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 to test PostgreSQL deletion",
)


def test_deletion_cascades_only_fixture_task_and_removes_its_checkpoint():
    async def verify():
        engine = create_database_engine(app_settings.database_url)
        try:
            async with engine.connect() as connection:
                outer = await connection.begin()
                factory = async_sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
                async with AsyncPostgresSaver.from_conn_string(app_settings.langgraph_database_url) as saver:
                    thread_id = None
                    try:
                        now = datetime.now(timezone.utc)
                        trace_id = uuid4()
                        async with factory() as session, session.begin():
                            task = LiteratureRunModel(status="queued", request={})
                            control = LiteratureRunModel(status="pending", request={})
                            paper = PaperModel(source="deletion-test", source_id=str(uuid4()), title="Rollback-only deletion fixture")
                            session.add_all([task, control, paper])
                            await session.flush()
                            run_id, control_id, paper_id = task.id, control.id, paper.id
                            session.add_all([
                                LiteratureRunPaperModel(run_id=run_id, paper_id=paper_id, position=0),
                                PaperSelectionModel(run_id=run_id, selected_paper_ids=[paper_id]),
                                ModuleWorkflowRunModel(literature_run_id=run_id, trace_id=trace_id, status="completed", deadline_at=now + timedelta(hours=1), finished_at=now),
                                WorkflowNodeExecutionModel(literature_run_id=run_id, trace_id=trace_id, node="finish", attempt=1, status="completed", duration_ms=0, input_summary={}, output_summary={}),
                            ])
                            code = CodeRunModel(literature_run_id=run_id, trace_id=trace_id, attempt=1, status="completed", request={}, started_at=now, finished_at=now)
                            validation = ValidationRunModel(literature_run_id=run_id, trace_id=trace_id, attempt=1, status="completed", request={}, started_at=now, finished_at=now)
                            session.add_all([code, validation])
                            await session.flush()
                            code_id, validation_id = code.id, validation.id
                            session.add_all([
                                CodeRunArtifactModel(code_run_id=code_id, paper_id=paper_id, position=0, artifact={}),
                                ValidationRunReportModel(validation_run_id=validation_id, paper_id=paper_id, position=0, report={}),
                            ])
                        thread_id = f"literature-run:{run_id}"
                        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                        checkpoint_config = await saver.aput(config, empty_checkpoint(), {}, {})
                        await saver.aput_writes(checkpoint_config, [("fixture", "safe")], "deletion-test")
                        assert await saver.aget_tuple(config) is not None
                        service = TaskDeletionService(SqlAlchemyTaskDeletionRepository(factory), saver.adelete_thread)
                        app = FastAPI()
                        app.include_router(literature_router, prefix="/api")
                        register_exception_handlers(app)
                        app.dependency_overrides[get_task_deletion_service] = lambda: service
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                            assert (await client.delete(f"/api/literature/runs/{run_id}")).status_code == 409
                            assert await saver.aget_tuple(config) is not None
                            async with factory() as session, session.begin():
                                task = await session.get(LiteratureRunModel, run_id)
                                task.status = "completed"
                            assert (await client.delete(f"/api/literature/runs/{run_id}")).status_code == 204
                            assert (await client.delete(f"/api/literature/runs/{run_id}")).status_code == 204
                        assert await saver.aget_tuple(config) is None
                        async with factory() as session:
                            assert await session.get(LiteratureRunModel, run_id) is None
                            assert await session.get(LiteratureRunModel, control_id) is not None
                            assert await session.get(PaperModel, paper_id) is not None
                            for model, column, value in [
                                (LiteratureRunPaperModel, LiteratureRunPaperModel.run_id, run_id),
                                (PaperSelectionModel, PaperSelectionModel.run_id, run_id),
                                (ModuleWorkflowRunModel, ModuleWorkflowRunModel.literature_run_id, run_id),
                                (WorkflowNodeExecutionModel, WorkflowNodeExecutionModel.literature_run_id, run_id),
                                (CodeRunModel, CodeRunModel.literature_run_id, run_id),
                                (ValidationRunModel, ValidationRunModel.literature_run_id, run_id),
                                (CodeRunArtifactModel, CodeRunArtifactModel.code_run_id, code_id),
                                (ValidationRunReportModel, ValidationRunReportModel.validation_run_id, validation_id),
                            ]:
                                assert await session.scalar(select(func.count()).select_from(model).where(column == value)) == 0
                    finally:
                        if thread_id is not None:
                            await saver.adelete_thread(thread_id)
                        await outer.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())
