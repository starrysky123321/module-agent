from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from module_agent.validation.domain.report import ValidationReport
from module_agent.validation.domain.request import ValidationRequest


class ValidationRunStatus(StrEnum):
    """定义可用的状态值。"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ValidationRun(BaseModel):
    """表示一次任务运行记录。"""
    # 记录主键。
    id: Annotated[int, Field(gt=0)] | None = None
    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 当前执行次数。
    attempt: Annotated[int, Field(ge=1)]
    # 跨服务追踪 ID。
    trace_id: UUID
    # 当前处理状态。
    status: ValidationRunStatus
    # 本次处理的输入请求。
    request: ValidationRequest
    # 结构化验证报告列表。
    reports: list[ValidationReport] = Field(default_factory=list)
    # 失败时的错误信息。
    error: str | None = None
    # 记录创建时间。
    created_at: AwareDatetime | None = None
    # 任务开始时间。
    started_at: AwareDatetime
    # 任务结束时间。
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        """校验状态与生命周期时间是否一致。"""
        if self.request.literature_run_id != self.literature_run_id:
            raise ValueError(
                "ValidationRun request belongs to another run"
            )

        if self.status is ValidationRunStatus.RUNNING:
            if self.finished_at is not None or self.error is not None:
                raise ValueError("Running ValidationRun cannot be finished")
            if self.reports:
                raise ValueError(
                    "Running ValidationRun cannot contain reports"
                )

        elif self.status is ValidationRunStatus.COMPLETED:
            if self.finished_at is None or not self.reports:
                raise ValueError(
                    "Completed ValidationRun requires reports and finished_at"
                )
            if self.error is not None:
                raise ValueError(
                    "Completed ValidationRun cannot contain an error"
                )

        elif self.status is ValidationRunStatus.FAILED:
            if self.finished_at is None or not self.error:
                raise ValueError(
                    "Failed ValidationRun requires error and finished_at"
                )

        elif self.status is ValidationRunStatus.CANCELLED:
            if self.finished_at is None:
                raise ValueError(
                    "Cancelled ValidationRun requires finished_at"
                )

        return self
