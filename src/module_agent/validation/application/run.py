from datetime import datetime, timezone
from uuid import UUID

from module_agent.validation.application.agent import ValidationAgent
from module_agent.validation.domain import (
    ValidationRequest,
    ValidationRun,
    ValidationRunRepository,
    ValidationRunStatus,
)
from module_agent.shared.exceptions import ValidationRunNotFoundError
from module_agent.shared.context import observability_context
from module_agent.shared.logging import logger


class ValidationRunService:
    """封装相关应用用例。"""
    def __init__(
        self,
        agent: ValidationAgent,
        repository: ValidationRunRepository,
    ) -> None:
        """初始化当前对象。"""
        self.agent = agent
        self.repository = repository

    async def execute(
        self,
        request: ValidationRequest,
        *,
        attempt: int,
        trace_id: UUID,
    ) -> ValidationRun:
        """执行当前用例。"""
        existing = await self.repository.get_by_execution(
            request.literature_run_id,
            attempt,
        )
        if existing is not None:
            if existing.status is ValidationRunStatus.COMPLETED:
                return existing
            raise RuntimeError(
                f"ValidationRun for attempt {attempt} is "
                f"already {existing.status.value}"
            )

        started_at = datetime.now(timezone.utc)
        run = await self.repository.save(
            ValidationRun(
                literature_run_id=request.literature_run_id,
                attempt=attempt,
                trace_id=trace_id,
                status=ValidationRunStatus.RUNNING,
                request=request,
                started_at=started_at,
            )
        )

        with observability_context(
            trace_id=trace_id,
            workflow_id=request.literature_run_id,
            agent_run_id=run.id,
        ):
            logger.info(
                "validation agent execution started | attempt={}",
                attempt,
            )
            try:
                reports = await self.agent.run(request)
            except Exception as exc:
                message = (str(exc).strip() or type(exc).__name__)[:1000]
                failed = ValidationRun.model_validate(
                    {
                        **run.model_dump(),
                        "status": ValidationRunStatus.FAILED,
                        "error": message,
                        "finished_at": datetime.now(timezone.utc),
                    }
                )
                await self.repository.save(failed)
                logger.exception("validation agent execution failed")
                raise

        completed = ValidationRun.model_validate(
            {
                **run.model_dump(),
                "status": ValidationRunStatus.COMPLETED,
                "reports": reports,
                "finished_at": datetime.now(timezone.utc),
            }
        )
        saved = await self.repository.save(completed)
        with observability_context(
            trace_id=trace_id,
            workflow_id=request.literature_run_id,
            agent_run_id=saved.id,
        ):
            if saved.finished_at is None:
                raise RuntimeError("Completed ValidationRun has no finished_at")
            duration_ms = (
                saved.finished_at - saved.started_at
            ).total_seconds() * 1000
            logger.info(
                "validation agent execution completed | attempt={} reports={} duration_ms={:.2f}",
                attempt,
                len(saved.reports),
                duration_ms,
            )
        return saved

    async def get_run(self, run_id: int) -> ValidationRun:
        """获取对应记录。"""
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("run_id must be a positive integer")
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise ValidationRunNotFoundError(run_id)
        return run

    async def list_runs(
        self,
        literature_run_id: int,
    ) -> list[ValidationRun]:
        """列出符合条件的记录。"""
        if type(literature_run_id) is not int or literature_run_id <= 0:
            raise ValueError(
                "literature_run_id must be a positive integer"
            )
        return await self.repository.list_by_literature_run(
            literature_run_id
        )
