from typing import Callable
from sqlalchemy.ext.asyncio import AsyncSession
from module_agent.literature.domain.jobs import LiteratureJobConsumer
from module_agent.literature.domain.jobs import LiteratureJob
from sqlalchemy.ext.asyncio import async_sessionmaker
from module_agent.literature.application.run import LiteratureRunService

class LiteratureDeadWorker:
    """处理后台任务。"""
    def __init__(self,  consumer: LiteratureJobConsumer, 
                 session_factory: async_sessionmaker[AsyncSession],
                 run_service_factory: Callable[[AsyncSession], LiteratureRunService]) -> None:
        """初始化当前对象。"""
        self.consumer = consumer
        self.session_factory = session_factory
        self.run_service_factory = run_service_factory
    
    
    async def run(self) -> None:
        """执行当前任务。"""
        await self.consumer.run(self._handle)
    
    
    async def _handle(self, job: LiteratureJob) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                run_service = self.run_service_factory(session)
                await run_service.fail_exhausted_run(
                    job.run_id,
                    "Literature job exceeded retry limit",
                )

                
