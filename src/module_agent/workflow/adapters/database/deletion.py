"""Transactional task deletion with execution-state guards."""

from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.code.adapters.database.models.run import CodeRunModel
from module_agent.literature.adapters.database.models.run import LiteratureRunModel
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.shared.exceptions import AppException
from module_agent.validation.adapters.database.models.run import ValidationRunModel
from module_agent.workflow.adapters.database.model import ModuleWorkflowRunModel
from module_agent.experiments.database import ExperimentJobModel
from module_agent.experiments.jobs import ACTIVE


class SqlAlchemyTaskDeletionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def delete_if_inactive(self, run_id: int) -> None:
        """Lock state rows and cascade only this task, never shared papers."""
        try:
            async with self.session_factory() as session, session.begin():
                status = await session.scalar(
                    select(LiteratureRunModel.status)
                    .where(LiteratureRunModel.id == run_id)
                    .with_for_update(nowait=True)
                )
                if status is None:
                    return  # Idempotent retry, including checkpoint cleanup.
                workflow_status = await session.scalar(
                    select(ModuleWorkflowRunModel.status)
                    .where(ModuleWorkflowRunModel.literature_run_id == run_id)
                    .with_for_update(nowait=True)
                )
                code_states = (await session.scalars(
                    select(CodeRunModel.status)
                    .where(CodeRunModel.literature_run_id == run_id)
                    .with_for_update(nowait=True)
                )).all()
                validation_states = (await session.scalars(
                    select(ValidationRunModel.status)
                    .where(ValidationRunModel.literature_run_id == run_id)
                    .with_for_update(nowait=True)
                )).all()
                inactive = {None, "waiting_for_selection", "completed", "failed", "cancelled", "timed_out"}
                active_experiment = await session.scalar(select(ExperimentJobModel.id).where(
                    ExperimentJobModel.literature_run_id == run_id,
                    ExperimentJobModel.status.in_(ACTIVE),
                ).limit(1))
                if (
                    active_experiment is not None
                    or
                    status in {LiteratureRunStatus.QUEUED, LiteratureRunStatus.RUNNING}
                    or workflow_status not in inactive
                    or any(state not in {"completed", "failed", "cancelled"} for state in code_states)
                    or any(state not in {"completed", "failed", "cancelled"} for state in validation_states)
                ):
                    raise AppException(
                        "任务仍在排队或执行，暂不能删除。请等待处理结束后重试。",
                        code="task_is_active", status_code=409,
                        details={"run_id": run_id},
                    )
                await session.execute(delete(LiteratureRunModel).where(LiteratureRunModel.id == run_id))
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise AppException("任务状态正在变更，请稍后重试删除。", code="task_is_busy", status_code=409) from exc
            raise
