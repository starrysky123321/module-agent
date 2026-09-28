from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ModuleWorkflowRunStatus(StrEnum):
    """定义可用的状态值。"""
    RUNNING = "running"
    WAITING_FOR_LITERATURE = "waiting_for_literature"
    WAITING_FOR_SELECTION = "waiting_for_selection"
    WAITING_FOR_CODE = "waiting_for_code"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class WorkflowControlStatus(StrEnum):
    """定义可用的状态值。"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ModuleWorkflowRun(BaseModel):
    """表示一次任务运行记录。"""
    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 跨服务追踪 ID。
    trace_id: UUID
    # 当前处理状态。
    status: ModuleWorkflowRunStatus
    # 任务截止时间。
    deadline_at: datetime
    # 用户请求取消的时间。
    cancellation_requested_at: datetime | None = None
    # 记录创建时间。
    created_at: datetime | None = None
    # 记录更新时间。
    updated_at: datetime | None = None
    # 任务结束时间。
    finished_at: datetime | None = None
    # 失败时的错误信息。
    error: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        """校验状态与生命周期时间是否一致。"""
        for name in (
            "deadline_at",
            "cancellation_requested_at",
            "created_at",
            "updated_at",
            "finished_at",
        ):
            value = getattr(self, name)
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")

        terminal = self.status in {
            ModuleWorkflowRunStatus.COMPLETED,
            ModuleWorkflowRunStatus.FAILED,
            ModuleWorkflowRunStatus.CANCELLED,
            ModuleWorkflowRunStatus.TIMED_OUT,
        }
        if terminal != (self.finished_at is not None):
            raise ValueError(
                "Terminal workflow status and finished_at must agree"
            )
        if (
            self.status is ModuleWorkflowRunStatus.CANCELLED
            and self.cancellation_requested_at is None
        ):
            raise ValueError(
                "Cancelled workflow requires cancellation timestamp"
            )
        return self


class ModuleWorkflowRunRepository(Protocol):
    """提供数据持久化访问能力。"""
    async def get(
        self,
        literature_run_id: int,
    ) -> ModuleWorkflowRun | None:
        """读取对应记录。"""
        ...

    async def save(
        self,
        run: ModuleWorkflowRun,
    ) -> ModuleWorkflowRun:
        """保存当前记录。"""
        ...


class WorkflowResumeRequest(BaseModel):
    """表示一次输入请求。"""
    # 操作超时时间，单位为秒。
    timeout_seconds: Annotated[int, Field(ge=1, le=86400)] | None = None
