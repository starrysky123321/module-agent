from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession
from module_agent.literature.application.execution import LiteratureRunExecutor
from module_agent.literature.domain.jobs import LiteratureJobConsumer
from module_agent.literature.domain.jobs import LiteratureJob
from module_agent.literature.domain.events import (
    LiteratureCompletionPublisher,
)
from module_agent.literature.domain.run import LiteratureRunStatus
from sqlalchemy.ext.asyncio import async_sessionmaker
from module_agent.shared.context import observability_context

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
            await self._execute(job)

    async def _execute(self, job: LiteratureJob) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                executor = self.executor_factory(session)
                run = await executor.get_run(job.run_id)
                already_completed = (
                    run.status is LiteratureRunStatus.COMPLETED
                )
                if not already_completed:
                    run = await executor.start(job.run_id)

        if already_completed:
            if job.resume_workflow:
                await self.completion_publisher.publish(job.run_id)
            return

        async with self.session_factory() as session:
            async with session.begin():
                executor = self.executor_factory(session)
                await executor.execute_started(run)

        if job.resume_workflow:
            await self.completion_publisher.publish(job.run_id)
