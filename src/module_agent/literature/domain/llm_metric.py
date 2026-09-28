from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class LlmCallOutcome(StrEnum):
    """封装 LlmCallOutcome 相关的数据和行为。"""
    SUCCESS = "success"
    FALLBACK = "fallback"


LlmCallStage = Literal[
    "query_planning",
    "relevance_scoring",
    "method_extraction",
]


class LlmCallMetric(BaseModel):
    """One model call, including a failed call recovered by a rule fallback."""

    # 模型调用所在的处理阶段。
    stage: LlmCallStage
    # 调用的模型名称。
    model: str
    # 本次模型调用处理的项目数量。
    item_count: Annotated[int, Field(ge=1)]
    # 操作耗时，单位为毫秒。
    duration_ms: Annotated[float, Field(ge=0)]
    # 操作超时时间，单位为秒。
    timeout_seconds: Annotated[float, Field(gt=0)]
    # 本次调用的结果状态。
    outcome: LlmCallOutcome
    # 失败异常的类型名称。
    error_type: str | None = None
    # 提供商返回的输入 token 数量；不支持时为零。
    prompt_tokens: Annotated[int, Field(ge=0)] = 0
    # 提供商返回的输出 token 数量；不支持时为零。
    completion_tokens: Annotated[int, Field(ge=0)] = 0
    # 提供商返回的总 token 数量；不支持时为零。
    total_tokens: Annotated[int, Field(ge=0)] = 0
