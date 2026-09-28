from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from module_agent.code.domain.artifact import CodeArtifact
from module_agent.code.domain.request import CodeAgentRequest


class CodeRunStatus(StrEnum):
    """定义可用的状态值。"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CodeRun(BaseModel):
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
    status: CodeRunStatus
    # 本次处理的输入请求。
    request: CodeAgentRequest
    # 等待处理的代码产物。
    artifacts: list[CodeArtifact] = Field(default_factory=list)
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
            raise ValueError("CodeRun request belongs to another run")

        if self.status is CodeRunStatus.RUNNING:
            if self.finished_at is not None or self.error is not None:
                raise ValueError("Running CodeRun cannot be finished")
            if self.artifacts:
                raise ValueError("Running CodeRun cannot contain artifacts")

        elif self.status is CodeRunStatus.COMPLETED:
            if self.finished_at is None or not self.artifacts:
                raise ValueError(
                    "Completed CodeRun requires artifacts and finished_at"
                )
            if self.error is not None:
                raise ValueError("Completed CodeRun cannot contain an error")

        elif self.status is CodeRunStatus.FAILED:
            if self.finished_at is None or not self.error:
                raise ValueError(
                    "Failed CodeRun requires error and finished_at"
                )

        elif self.status is CodeRunStatus.CANCELLED:
            if self.finished_at is None:
                raise ValueError(
                    "Cancelled CodeRun requires finished_at"
                )

        return self
