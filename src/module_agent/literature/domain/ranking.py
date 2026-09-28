from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Protocol

from pydantic import BaseModel, Field
from module_agent.literature.domain.llm_metric import LlmCallMetric

if TYPE_CHECKING:
    from module_agent.literature.domain.search import PaperSearchResult, SearchRequest


class PaperRelevanceAssessment(BaseModel):
    """一篇候选论文与用户检索需求的相关性评估。"""

    # 数据来源。
    source: Annotated[str, Field(min_length=1)]
    # 数据来源中的唯一标识。
    source_id: Annotated[str, Field(min_length=1)]
    # 论文相关性分数。
    score: Annotated[float, Field(ge=0.0, le=1.0)]
    # 匹配到的检索词。
    matched_terms: list[str] = Field(default_factory=list)
    # 生成当前结果的原因。
    reason: str = ""


class PaperRelevanceResult(BaseModel):
    """一次候选论文批量评分的结果及其降级提示。"""

    # 论文相关性评估列表。
    assessments: list[PaperRelevanceAssessment] = Field(
        default_factory=list
    )
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 各阶段模型调用指标。
    llm_metrics: list[LlmCallMetric] = Field(default_factory=list)


class PaperRelevanceScorer(Protocol):
    """候选论文批量相关性评分器的领域接口。"""

    async def score_many(
        self,
        request: SearchRequest,
        search_queries: Sequence[str],
        papers: Sequence[PaperSearchResult],
    ) -> PaperRelevanceResult:
        """批量评估候选论文与检索需求的相关性。"""
        ...
