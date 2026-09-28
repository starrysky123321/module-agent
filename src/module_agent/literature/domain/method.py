from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field
from module_agent.literature.domain.llm_metric import LlmCallMetric

if TYPE_CHECKING:
    from module_agent.literature.domain.search import PaperSearchResult, SearchRequest


class PaperEvidence(BaseModel):
    """表示支撑判断的一条证据。"""
    # 该证据对应的方法画像字段。
    field: Literal["title", "abstract"]
    # 支持画像结论的原文片段。
    excerpt: str


class PaperMethodProfile(BaseModel):
    """保存结构化分析画像。"""
    # 数据来源。
    source: str
    # 数据来源中的唯一标识。
    source_id: str

    # 论文希望解决的研究问题。
    research_problem: str | None = None
    # 论文方法所属的模块类型。
    module_type: str | None = None
    # 论文提出的核心方法。
    core_method: str | None = None

    # 方法所需的输入。
    inputs: list[str] = Field(default_factory=list)
    # 方法产生的输出。
    outputs: list[str] = Field(default_factory=list)
    # 该方法适用的任务。
    applicable_tasks: list[str] = Field(default_factory=list)

    # 支撑判断的证据列表。
    evidence: list[PaperEvidence] = Field(default_factory=list)
    # 当前结果的可信度。
    confidence: float = Field(ge=0.0, le=1.0)


class PaperMethodExtractionResult(BaseModel):
    """表示一次处理结果。"""
    # 论文方法画像列表。
    profiles: list[PaperMethodProfile] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 各阶段模型调用指标。
    llm_metrics: list[LlmCallMetric] = Field(default_factory=list)


class PaperMethodExtractor(Protocol):
    """封装 PaperMethodExtractor 相关的数据和行为。"""
    async def extract_many(
        self,
        request: SearchRequest,
        papers: Sequence[PaperSearchResult],
    ) -> PaperMethodExtractionResult:
        """批量提取结构化信息。"""
        ...
