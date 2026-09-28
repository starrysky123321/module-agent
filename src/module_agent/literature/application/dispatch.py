from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.domain.jobs import LiteratureJobQueue
from uuid import UUID



class LiteratureRunDispatcher:
    """封装 LiteratureRunDispatcher 相关的数据和行为。"""
    def __init__(
        self,
        run_service: LiteratureRunService,
        job_queue: LiteratureJobQueue,
    ) -> None:
        """初始化当前对象。"""
        self.run_service = run_service
        self.job_queue = job_queue

    async def dispatch(
        self,
        run_id: int,
        resume_workflow: bool = False,
        trace_id: UUID | None = None,
    ) -> str:
        """分发当前任务。"""
        queued_run = await self.run_service.queue_run(run_id)
        
        if queued_run.id is None:
            raise RuntimeError("Queued literature run is missing id")
        
        if trace_id is None:
            message_id = await self.job_queue.enqueue(
                queued_run.id,
                resume_workflow=resume_workflow,
            )
        else:
            message_id = await self.job_queue.enqueue(
                queued_run.id,
                resume_workflow=resume_workflow,
                trace_id=trace_id,
            )
        
        return message_id
