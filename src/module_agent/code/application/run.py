from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
import math
from uuid import UUID

from module_agent.code.application.agent import CodeAgent
from module_agent.code.domain import (
    CodeAgentRequest,
    CodeRun,
    CodeRunRepository,
    CodeRunStatus,
)
from module_agent.code.domain.ports import PaperCodeStatusWriter
from module_agent.shared.exceptions import CodeRunNotFoundError
from module_agent.shared.context import observability_context
from module_agent.shared.logging import logger
from module_agent.shared.redaction import redact_sensitive_text
from module_agent.shared.execution_control import ExecutionStopped, run_with_control


class CodeRunService:
    """封装相关应用用例。"""

    def __init__(
        self,
        agent: CodeAgent,
        repository: CodeRunRepository,
        paper_code_status_writer: PaperCodeStatusWriter | None = None,
        *,
        execution_control: Callable[[int], Awaitable[bool]] | None = None,
        control_poll_seconds: float = 1.0,
    ) -> None:
        """初始化当前对象。"""
        self.agent = agent
        self.repository = repository
        self.paper_code_status_writer = paper_code_status_writer
        if not math.isfinite(control_poll_seconds) or control_poll_seconds <= 0:
            raise ValueError("Control poll interval must be positive")
        self.execution_control = execution_control
        self.control_poll_seconds = control_poll_seconds

    async def _execute_agent(self, request: CodeAgentRequest):
        """持续读取取消/期限状态，并取消本地等待、子进程及排队论文。"""
        control = self.execution_control
        return await run_with_control(
            lambda: self.agent.run(request),
            (lambda: control(request.literature_run_id))
            if control is not None
            else None,
            poll_seconds=self.control_poll_seconds,
        )

    async def execute(
        self,
        request: CodeAgentRequest,
        *,
        attempt: int,
        trace_id: UUID,
    ) -> CodeRun:
        """执行当前用例。"""
        existing = await self.repository.get_by_execution(
            request.literature_run_id,
            attempt,
        )
        if existing is not None:
            if existing.status in {CodeRunStatus.COMPLETED, CodeRunStatus.CANCELLED}:
                return existing
            raise RuntimeError(
                f"CodeRun for attempt {attempt} is already {existing.status.value}"
            )

        started_at = datetime.now(timezone.utc)
        run = await self.repository.save(
            CodeRun(
                literature_run_id=request.literature_run_id,
                attempt=attempt,
                trace_id=trace_id,
                status=CodeRunStatus.RUNNING,
                request=request,
                started_at=started_at,
            )
        )

        with observability_context(
            trace_id=trace_id,
            workflow_id=request.literature_run_id,
            agent_run_id=run.id,
        ):
            logger.info("code agent execution started | attempt={}", attempt)
            try:
                artifacts = await self._execute_agent(request)
            except ExecutionStopped as exc:
                cancelled = CodeRun.model_validate(
                    {
                        **run.model_dump(),
                        "status": CodeRunStatus.CANCELLED,
                        "error": str(exc),
                        "finished_at": datetime.now(timezone.utc),
                    }
                )
                logger.info("code agent execution stopped | attempt={}", attempt)
                return await self.repository.save(cancelled)
            except Exception as exc:
                message = redact_sensitive_text(str(exc).strip() or type(exc).__name__)[
                    :1000
                ]
                failed = CodeRun.model_validate(
                    {
                        **run.model_dump(),
                        "status": CodeRunStatus.FAILED,
                        "error": message,
                        "finished_at": datetime.now(timezone.utc),
                    }
                )
                await self.repository.save(failed)
                logger.exception("code agent execution failed")
                raise

        completed = CodeRun.model_validate(
            {
                **run.model_dump(),
                "status": CodeRunStatus.COMPLETED,
                "artifacts": artifacts,
                "finished_at": datetime.now(timezone.utc),
            }
        )
        saved = await self.repository.save(completed)
        if self.paper_code_status_writer is not None:
            try:
                await self.paper_code_status_writer.write(saved.artifacts)
            except Exception as exc:
                logger.warning(
                    "paper code availability sync failed | error_type={} error={}",
                    type(exc).__name__,
                    str(exc),
                )
        with observability_context(
            trace_id=trace_id,
            workflow_id=request.literature_run_id,
            agent_run_id=saved.id,
        ):
            if saved.finished_at is None:
                raise RuntimeError("Completed CodeRun has no finished_at")
            duration_ms = (saved.finished_at - saved.started_at).total_seconds() * 1000
            logger.info(
                "code agent execution completed | attempt={} artifacts={} duration_ms={:.2f}",
                attempt,
                len(saved.artifacts),
                duration_ms,
            )
        return saved

    async def get_run(self, run_id: int) -> CodeRun:
        """获取对应记录。"""
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("run_id must be a positive integer")
        run = await self.repository.get_by_id(run_id)
        if run is None:
            raise CodeRunNotFoundError(run_id)
        return run

    async def list_runs(self, literature_run_id: int) -> list[CodeRun]:
        """列出符合条件的记录。"""
        if type(literature_run_id) is not int or literature_run_id <= 0:
            raise ValueError("literature_run_id must be a positive integer")
        return await self.repository.list_by_literature_run(literature_run_id)
