"""可持久化的模型调用数据，不依赖 HTTP、日志或客户端实现。"""

from typing import Annotated, Literal
from pydantic import BaseModel, Field


class ModelCallMetric(BaseModel):
    stage: str
    model: str
    outcome: Literal["success", "failed", "timeout", "cancelled"]
    duration_ms: Annotated[float, Field(ge=0)]
    timeout_seconds: Annotated[float, Field(gt=0)]
    error_type: str | None = None
    prompt_tokens: Annotated[int | None, Field(ge=0)] = None
    completion_tokens: Annotated[int | None, Field(ge=0)] = None
    total_tokens: Annotated[int | None, Field(ge=0)] = None
