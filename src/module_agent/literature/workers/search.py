from collections.abc import Callable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.literature.adapters.database.models.messaging import LiteratureJobInboxModel
from module_agent.literature.application.execution import LiteratureRunExecutor
from module_agent.literature.domain.jobs import LiteratureJobConsumer
from module_agent.literature.domain.jobs import LiteratureJob
from module_agent.literature.domain.events import (
    LiteratureCompletionPublisher,
)
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.shared.context import observability_context
from module_agent.shared.execution_control import ExecutionStopped
from module_agent.shared.exceptions import LiteratureRunNotFoundError
from module_agent.shared.idempotency import IdempotencyOperation, idempotency_key
from module_agent.shared.logging import logger

LiteratureRunExecutorFactory = Callable[
    [AsyncSession],
    LiteratureRunExecutor,
]


class LiteratureWorker:
    """处理后台任务。"""
    def __init__(
        self,
        consumer: LiteratureJobConsumer,
        completion_publisher: LiteratureCompletionPublisher,
        session_factory: async_sessionmaker[AsyncSession],
        executor_factory: LiteratureRunExecutorFactory,
    ) -> None:
        """初始化当前对象。"""
        self.consumer = consumer
        self.completion_publisher = completion_publisher
        self.session_factory = session_factory
        self.executor_factory = executor_factory

    async def run(self) -> None:
        """执行当前任务。"""
        await self.consumer.run(self._handle)

    async def _handle(self, job: LiteratureJob) -> None:
        with observability_context(
            trace_id=job.trace_id,
            workflow_id=job.run_id,
            message_id=job.message_id,
        ):
            if job.message_id is not None:
                logger.info(
                    "literature delivery received | idempotency_key={}",
                    idempotency_key(IdempotencyOperation.LITERATURE_CONSUME, job.run_id, job.message_id),
                )
            await self._execute(job)

    async def _execute(self, job: LiteratureJob) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                executor = self.executor_factory(session)
                try:
                    run = await executor.get_run(job.run_id)
                except LiteratureRunNotFoundError:
                    return  # A delivery already in RabbitMQ can outlive a deleted task.
                already_completed = (
                    run.status in {LiteratureRunStatus.COMPLETED, LiteratureRunStatus.CANCELLED}
                )
                if not already_completed:
                    run = await executor.start(job.run_id)

        if already_completed:
            if job.resume_workflow:
                await self.completion_publisher.publish(job.run_id)
            return

        async with self.session_factory() as session:
            async with session.begin():
                if job.message_id is None or await self._claim_message(session, job):
                    executor = self.executor_factory(session)
                    try:
                        await executor.execute_started(run)
                    except ExecutionStopped:
                        pass  # 在事务内提交 cancelled，取消消息也可以安全确认。

        if job.resume_workflow:
            await self.completion_publisher.publish(job.run_id)


    @staticmethod
    async def _claim_message(session: AsyncSession, job: LiteratureJob) -> bool:
        """Commit the receipt with the search results; rollback allows redelivery."""
        statement = (
            insert(LiteratureJobInboxModel)
            .values(run_id=job.run_id, message_id=job.message_id)
            .on_conflict_do_nothing(index_elements=["run_id", "message_id"])
            .returning(LiteratureJobInboxModel.message_id)
        )
        return await session.scalar(statement) is not None
