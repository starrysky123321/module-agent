from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.literature.domain.events import (
    LiteratureCompletedEvent,
    LiteratureCompletionConsumer,
)
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)


ModuleWorkflowCoordinatorFactory = Callable[
    [AsyncSession],
    ModuleWorkflowCoordinator,
]


class LiteratureCompletionWorker:
    """处理后台任务。"""
    def __init__(
        self,
        consumer: LiteratureCompletionConsumer,
        session_factory: async_sessionmaker[AsyncSession],
        coordinator_factory: ModuleWorkflowCoordinatorFactory,
    ) -> None:
        """初始化当前对象。"""
        self.consumer = consumer
        self.session_factory = session_factory
        self.coordinator_factory = coordinator_factory

    async def run(self) -> None:
        """执行当前任务。"""
        await self.consumer.run(self._handle)

    async def _handle(self, event: LiteratureCompletedEvent) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                coordinator = self.coordinator_factory(session)
                await coordinator.resume_after_literature_completion(
                    event.run_id
                )
