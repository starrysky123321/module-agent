"""Real SQL claims, consent and deletion guards; rollback-only, no training."""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from module_agent.bootstrap import database_models  # noqa: F401
from module_agent.experiments.database import ExperimentJobModel, ExperimentWorkerModel
from module_agent.experiments.domain import ExperimentBudget
from module_agent.experiments.jobs import PilotApproval, PilotRequest
from module_agent.experiments.recipe import TITLE
from module_agent.experiments.worker import ExperimentWorker
from module_agent.literature.adapters.database.models.paper import PaperModel
from module_agent.literature.adapters.database.models.run import LiteratureRunModel, LiteratureRunPaperModel
from module_agent.literature.adapters.database.models.selection import PaperSelectionModel
from module_agent.shared.config import app_settings
from module_agent.shared.database.session import create_database_engine
from module_agent.shared.exceptions import AppException
from module_agent.shared.resources import ResourceSnapshot, GpuResource
from module_agent.workflow.adapters.database.deletion import SqlAlchemyTaskDeletionRepository
from module_agent.workflow.adapters.database.model import ModuleWorkflowRunModel
from module_agent.workflow.experiments import WorkflowExperimentService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1", reason="requires PostgreSQL integration opt-in")


def test_approved_job_can_be_claimed_once_and_never_replayed(tmp_path):
    async def check():
        engine = create_database_engine(app_settings.database_url)
        try:
            async with engine.connect() as connection:
                outer = await connection.begin()
                factory = async_sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
                service = WorkflowExperimentService(factory)
                worker = ExperimentWorker(factory, tmp_path)
                now = datetime.now(timezone.utc)
                snapshot = ResourceSnapshot(scope="host", logical_cpu_count=8, available_cpu_count=8,
                    memory_available_mb=8192, workspace_free_mb=65536, gpu_status="detected", sandbox_ready=True,
                    gpus=[GpuResource(index=0, uuid="GPU-synthetic", name="synthetic")])
                async with factory() as s, s.begin():
                    task = LiteratureRunModel(status="completed", request={})
                    paper = PaperModel(source="experiment-test", source_id=str(uuid4()), title=TITLE)
                    unrelated = PaperModel(source="experiment-test", source_id=str(uuid4()), title="Different paper")
                    s.add_all([task, paper, unrelated])
                    await s.flush()
                    run_id, paper_id = task.id, paper.id
                    s.add_all([LiteratureRunPaperModel(run_id=run_id, paper_id=paper_id, position=0),
                        PaperSelectionModel(run_id=run_id, selected_paper_ids=[paper_id]),
                        ModuleWorkflowRunModel(literature_run_id=run_id, trace_id=uuid4(), status="completed", deadline_at=now + timedelta(hours=1)),
                        ExperimentWorkerModel(id=worker.id, resources=snapshot.model_dump(mode="json"), heartbeat_at=now)])
                request = PilotRequest(paper_id=paper_id, worker_id=worker.id, budget=ExperimentBudget(gpu_uuid="GPU-synthetic"))
                with pytest.raises(AppException):
                    await service.propose(run_id, request.model_copy(update={"paper_id": unrelated.id}))
                draft = await service.propose(run_id, request)
                assert draft.status == "draft" and await worker.claim() is None
                approval = PilotApproval(proposal_sha256=draft.proposal_sha256, execute_code=True, allow_preparation_network=True,
                    acknowledge_source_license=True, acknowledge_gpu_not_memory_capped=True)
                with pytest.raises(AppException):
                    await service.confirm(draft.id, approval.model_copy(update={"proposal_sha256": "0" * 64}))
                assert (await service.confirm(draft.id, approval)).status == "queued"
                assert (await service.confirm(draft.id, approval)).id == draft.id
                second = await service.propose(run_id, request)
                with pytest.raises(AppException):
                    await service.confirm(second.id, approval.model_copy(update={"proposal_sha256": second.proposal_sha256}))
                with pytest.raises(AppException):
                    await SqlAlchemyTaskDeletionRepository(factory).delete_if_inactive(run_id)
                claimed = await worker.claim()
                assert claimed and claimed.id == draft.id
                assert await worker.claim() is None
                worker.current = draft.id
                assert await worker.allowed()
                await service.cancel(draft.id)
                await worker.publish(status="running", stage="train")
                assert not await worker.allowed()  # Publication cannot erase cancellation.
                await worker.publish(status="cancelled", stage="cancelled")
                # Stale work is marked interrupted, never queued again.
                third = await service.propose(run_id, request)
                await service.confirm(third.id, approval.model_copy(update={"proposal_sha256": third.proposal_sha256}))
                async with factory() as s, s.begin():
                    w = await s.get(ExperimentWorkerModel, worker.id)
                    w.heartbeat_at = now - timedelta(minutes=5)
                    job = await s.get(ExperimentJobModel, third.id)
                    job.updated_at = now - timedelta(minutes=5)
                overview = await service.overview(run_id)
                assert next(j for j in overview["jobs"] if j.id == third.id).status == "interrupted"
                assert await worker.claim() is None
                await SqlAlchemyTaskDeletionRepository(factory).delete_if_inactive(run_id)
                async with factory() as s:
                    assert not (await s.scalars(select(ExperimentJobModel).where(ExperimentJobModel.literature_run_id == run_id))).all()
                    assert await s.get(PaperModel, paper_id) is not None
                await outer.rollback()
        finally:
            await engine.dispose()
    asyncio.run(check())
