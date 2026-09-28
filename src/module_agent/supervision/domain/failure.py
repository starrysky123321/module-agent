from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    model_validator,
)

from module_agent.workflow.domain import SupervisorStep

FailureMessage = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=1000,
    ),
]

ErrorType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
    ),
]


class WorkflowFailureCategory(StrEnum):
    """封装 WorkflowFailureCategory 相关的数据和行为。"""
    TRANSIENT_EXTERNAL = "transient_external"
    TIMEOUT = "timeout"
    CONFIGURATION = "configuration"
    INVALID_STATE = "invalid_state"
    INTERNAL = "internal"


class WorkflowFailure(BaseModel):
    """描述一次结构化失败。"""
    # 失败发生的工作流阶段。
    step: SupervisorStep
    # 记录所属的业务分类。
    category: WorkflowFailureCategory
    # 面向用户或日志的说明。
    message: FailureMessage
    # 当前失败是否允许重试。
    retryable: bool = False
    # 当前执行次数。
    attempt: Annotated[int, Field(ge=1)] = 1
    # 失败异常的类型名称。
    error_type: ErrorType | None = None

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """校验多个字段之间的一致性。"""
        if (
            self.category
            in {
                WorkflowFailureCategory.CONFIGURATION,
                WorkflowFailureCategory.INVALID_STATE,
            }
            and self.retryable
        ):
            raise ValueError(
                "Configuration and invalid-state failures cannot be retried"
            )

        return self
