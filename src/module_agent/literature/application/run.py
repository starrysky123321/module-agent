from module_agent.literature.domain.repositories.run import LiteratureRunRepository
from module_agent.literature.domain.run import LiteratureRun
from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.search import SourceSearchMetric
from module_agent.literature.domain.llm_metric import LlmCallMetric
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.shared.exceptions import (
    LiteratureRunNotFoundError,
    LiteratureRunStateError,
)
from datetime import datetime, timezone


class LiteratureRunService:
    """封装相关应用用例。"""
    def __init__(self, repository: LiteratureRunRepository) -> None:
        """初始化当前对象。"""
        self.repository = repository
    
    async def create_run(self, request: SearchRequest) -> LiteratureRun:
        """创建对应记录。"""
        run = LiteratureRun(request=request)
        return await self.repository.save(run)
        
    async def start_run(self, run_id: int) -> LiteratureRun:
        """启动当前流程。"""
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise LiteratureRunNotFoundError(run_id)
        if run.status is LiteratureRunStatus.RUNNING:
            return run
        if run.status not in (
            LiteratureRunStatus.PENDING,
            LiteratureRunStatus.QUEUED,
        ):
            raise LiteratureRunStateError(run_id, "start")
        run.status = LiteratureRunStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        return await self.repository.save(run)

    
    async def complete_run(
        self,
        run_id: int,
        search_queries: list[str],
        papers: list[LiteratureRunPaper],
        warnings: list[str],
        source_metrics: list[SourceSearchMetric] | None = None,
        llm_metrics: list[LlmCallMetric] | None = None,
    ) -> LiteratureRun:
        """把任务更新为完成状态。"""
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise LiteratureRunNotFoundError(run_id)
        if run.status != LiteratureRunStatus.RUNNING:
            raise LiteratureRunStateError(run_id, "complete")
        run.status = LiteratureRunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        run.search_queries = search_queries
        run.warnings = warnings
        run.source_metrics = list(source_metrics or [])
        run.llm_metrics = list(llm_metrics or [])
        await self.repository.replace_papers(run_id, papers)
        return await self.repository.save(run)


    async def fail_run(
        self,
        run_id: int,
        error: str,
    ) -> LiteratureRun:
        """把任务更新为失败状态。"""
        normalized_error = error.strip()
        if not normalized_error:
            raise ValueError("Error message cannot be empty")
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise LiteratureRunNotFoundError(run_id)
        if run.status != LiteratureRunStatus.RUNNING:
            raise LiteratureRunStateError(run_id, "fail")
        run.status = LiteratureRunStatus.FAILED
        run.error = normalized_error
        run.completed_at = datetime.now(timezone.utc)
        return await self.repository.save(run)
    
    
    async def cancel_run(self, run_id: int) -> LiteratureRun:
        """取消当前流程。"""
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise LiteratureRunNotFoundError(run_id)
        if run.status not in (
            LiteratureRunStatus.PENDING,
            LiteratureRunStatus.QUEUED,
            LiteratureRunStatus.RUNNING,
        ):
            raise LiteratureRunStateError(run_id, "cancel")
        run.status = LiteratureRunStatus.CANCELLED
        run.completed_at = datetime.now(timezone.utc)
        return await self.repository.save(run)


    async def get_run(self, run_id: int) -> LiteratureRun:
        """获取对应记录。"""
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise LiteratureRunNotFoundError(run_id)
        return run


    async def queue_run(self, run_id: int) -> LiteratureRun:
        """把任务更新为排队状态。"""
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise LiteratureRunNotFoundError(run_id)
        if run.status != LiteratureRunStatus.PENDING:
            raise LiteratureRunStateError(run_id, "queue")
        run.status = LiteratureRunStatus.QUEUED
        return await self.repository.save(run)
    
    
    async def fail_exhausted_run(
        self,
        run_id: int,
        error: str,
    ) -> LiteratureRun:
        """把任务更新为失败状态。"""
        normalized_error = error.strip()
        if not normalized_error:
            raise ValueError("Error message cannot be empty")
        
        run = await self.get_run(run_id)
        
        if run.status == LiteratureRunStatus.FAILED:
            return run
        
        if run.status not in (LiteratureRunStatus.RUNNING,
                              LiteratureRunStatus.QUEUED):
            raise LiteratureRunStateError(run_id, "fail after retry exhaustion")
        
        run.status = LiteratureRunStatus.FAILED
        run.error = normalized_error
        run.completed_at = datetime.now(timezone.utc)
        return await self.repository.save(run)
