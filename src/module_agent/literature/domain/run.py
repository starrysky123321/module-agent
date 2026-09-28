from enum import StrEnum
from datetime import datetime
from pydantic import BaseModel, Field
from module_agent.literature.domain.search import SearchRequest, SourceSearchMetric
from module_agent.literature.domain.llm_metric import LlmCallMetric



class LiteratureRunStatus(StrEnum):
      """定义可用的状态值。"""
      PENDING = "pending"
      QUEUED = "queued"
      RUNNING = "running"
      COMPLETED = "completed"
      FAILED = "failed"
      CANCELLED = "cancelled"
      

class LiteratureRun(BaseModel):
    """表示一次任务运行记录。"""
    # 记录主键。
    id: int | None = None
    # 当前处理状态。
    status: LiteratureRunStatus = LiteratureRunStatus.PENDING

    # 本次处理的输入请求。
    request: SearchRequest
    # 本次实际使用的检索词。
    search_queries: list[str] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 各文献来源的调用指标。
    source_metrics: list[SourceSearchMetric] = Field(default_factory=list)
    # 各阶段模型调用指标。
    llm_metrics: list[LlmCallMetric] = Field(default_factory=list)

    # 失败时的错误信息。
    error: str | None = None

    # 记录创建时间。
    created_at: datetime | None = None
    # 任务开始时间。
    started_at: datetime | None = None
    # 任务完成时间。
    completed_at: datetime | None = None
