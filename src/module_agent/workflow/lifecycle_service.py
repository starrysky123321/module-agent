from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from module_agent.shared.exceptions import (
    WorkflowControlError,
    WorkflowLifecycleNotFoundError,
)
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    ModuleWorkflowRunRepository,
    ModuleWorkflowRunStatus,
    WorkflowControlStatus,
)


class ModuleWorkflowLifecycleService:
    """封装相关应用用例。"""
    def __init__(
        self,
        repository: ModuleWorkflowRunRepository,
        *,
        default_timeout_seconds: int,
    ) -> None:
        """初始化当前对象。"""
        if default_timeout_seconds < 1:
            raise ValueError("default_timeout_seconds must be positive")
        self.repository = repository
        self.default_timeout_seconds = default_timeout_seconds

    async def start(
        self,
        literature_run_id: int,
        *,
        timeout_seconds: int | None = None,
        trace_id: UUID | None = None,
    ) -> ModuleWorkflowRun:
        """启动当前流程。"""
        existing = await self.repository.get(literature_run_id)
        if existing is not None:
            return existing

        timeout = (
            self.default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if timeout < 1:
            raise ValueError("timeout_seconds must be positive")
        now = datetime.now(timezone.utc)
        return await self.repository.save(
            ModuleWorkflowRun(
                literature_run_id=literature_run_id,
                trace_id=trace_id or uuid4(),
                status=ModuleWorkflowRunStatus.RUNNING,
                deadline_at=now + timedelta(seconds=timeout),
            )
        )

    async def get(self, literature_run_id: int) -> ModuleWorkflowRun:
        """读取对应记录。"""
        run = await self.repository.get(literature_run_id)
        if run is None:
            raise WorkflowLifecycleNotFoundError(literature_run_id)
        return run

    async def set_status(
        self,
        literature_run_id: int,
        status: ModuleWorkflowRunStatus,
        *,
        error: str | None = None,
    ) -> ModuleWorkflowRun:
        """更新工作流生命周期状态。"""
        run = await self.get(literature_run_id)
        if run.status in _TERMINAL_STATUSES:
            return run
        if run.status is status and run.error == error:
            return run  # Repeated callbacks must not reset the pause clock.
        now = datetime.now(timezone.utc)
        deadline = run.deadline_at
        pause_started = run.selection_wait_started_at
        if run.status is ModuleWorkflowRunStatus.WAITING_FOR_SELECTION:
            # updated_at covers legacy selection waits created before this field.
            pause_started = pause_started or run.updated_at or now
            if status is not ModuleWorkflowRunStatus.WAITING_FOR_SELECTION:
                deadline += max(now - pause_started, timedelta())
                pause_started = None
        elif status is ModuleWorkflowRunStatus.WAITING_FOR_SELECTION:
            if now >= deadline:
                # Do not forgive a real execution timeout before human waiting.
                status = ModuleWorkflowRunStatus.TIMED_OUT
                error = "Workflow deadline exceeded"
            else:
                pause_started = now
        finished_at = (
            now
            if status in _TERMINAL_STATUSES
            else None
        )
        updated = ModuleWorkflowRun.model_validate(
            {
                **run.model_dump(),
                "status": status,
                "deadline_at": deadline,
                "selection_wait_started_at": pause_started if status is ModuleWorkflowRunStatus.WAITING_FOR_SELECTION else None,
                "finished_at": finished_at,
                "error": error,
            }
        )
        return await self.repository.save(updated)

    async def cancel(self, literature_run_id: int) -> ModuleWorkflowRun:
        """取消当前流程。"""
        run = await self.get(literature_run_id)
        if run.status in _TERMINAL_STATUSES:
            if run.status is ModuleWorkflowRunStatus.CANCELLED:
                return run
            raise WorkflowControlError(
                literature_run_id,
                f"cannot cancel workflow in {run.status.value} state",
            )
        now = datetime.now(timezone.utc)
        cancelled = ModuleWorkflowRun.model_validate(
            {
                **run.model_dump(),
                "status": ModuleWorkflowRunStatus.CANCELLED,
                "cancellation_requested_at": now,
                "finished_at": now,
                "selection_wait_started_at": None,
            }
        )
        return await self.repository.save(cancelled)

    async def check_control(
        self,
        literature_run_id: int,
    ) -> WorkflowControlStatus:
        """执行对应检查。"""
        run = await self.get(literature_run_id)
        if run.status is ModuleWorkflowRunStatus.CANCELLED:
            return WorkflowControlStatus.CANCELLED
        if run.status is ModuleWorkflowRunStatus.TIMED_OUT:
            return WorkflowControlStatus.TIMED_OUT
        if run.status in {
            ModuleWorkflowRunStatus.COMPLETED,
            ModuleWorkflowRunStatus.FAILED,
        }:
            return WorkflowControlStatus.ACTIVE
        if run.status is ModuleWorkflowRunStatus.WAITING_FOR_SELECTION:
            pause_started = run.selection_wait_started_at or run.updated_at
            if pause_started is not None and pause_started < run.deadline_at:
                return WorkflowControlStatus.ACTIVE

        if datetime.now(timezone.utc) >= run.deadline_at:
            await self.set_status(
                literature_run_id,
                ModuleWorkflowRunStatus.TIMED_OUT,
                error="Workflow deadline exceeded",
            )
            return WorkflowControlStatus.TIMED_OUT
        return WorkflowControlStatus.ACTIVE

    async def resume_timed_out(
        self,
        literature_run_id: int,
        *,
        status: ModuleWorkflowRunStatus,
        timeout_seconds: int | None = None,
    ) -> ModuleWorkflowRun:
        """恢复暂停的流程。"""
        run = await self.get(literature_run_id)
        if run.status is not ModuleWorkflowRunStatus.TIMED_OUT:
            raise WorkflowControlError(
                literature_run_id,
                "only a timed-out workflow can be resumed",
            )
        if status not in {
            ModuleWorkflowRunStatus.WAITING_FOR_LITERATURE,
            ModuleWorkflowRunStatus.WAITING_FOR_SELECTION,
            ModuleWorkflowRunStatus.WAITING_FOR_CODE,
        }:
            raise ValueError("Timed-out workflow must resume at a wait point")
        timeout = (
            self.default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if timeout < 1:
            raise ValueError("timeout_seconds must be positive")
        now = datetime.now(timezone.utc)
        resumed = ModuleWorkflowRun.model_validate(
            {
                **run.model_dump(),
                "status": status,
                "deadline_at": (
                    now
                    + timedelta(seconds=timeout)
                ),
                "finished_at": None,
                "selection_wait_started_at": now if status is ModuleWorkflowRunStatus.WAITING_FOR_SELECTION else None,
                "error": None,
            }
        )
        return await self.repository.save(resumed)


_TERMINAL_STATUSES = frozenset(
    {
        ModuleWorkflowRunStatus.COMPLETED,
        ModuleWorkflowRunStatus.FAILED,
        ModuleWorkflowRunStatus.CANCELLED,
        ModuleWorkflowRunStatus.TIMED_OUT,
    }
)
