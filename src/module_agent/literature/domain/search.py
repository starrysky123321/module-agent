from datetime import date
from enum import StrEnum
from typing import Annotated, Any, NotRequired, TypedDict

from pydantic import BaseModel, Field, model_validator

from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.ranking import PaperRelevanceAssessment
from module_agent.literature.domain.method import PaperMethodProfile
from module_agent.literature.domain.llm_metric import LlmCallMetric


class SourceSearchOutcome(StrEnum):
    """封装 SourceSearchOutcome 相关的数据和行为。"""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class VenueQualityRequirement(BaseModel):
    """用户对期刊或会议评级的筛选要求。"""

    # 评级体系名称。
    ranking_system: Annotated[str, Field(min_length=1, max_length=50)]
    # 用户接受的会议期刊评级。
    allowed_levels: Annotated[list[str], Field(min_length=1, max_length=20)]


class SearchRequest(BaseModel):
    """表示一次输入请求。"""
    # 用户希望检索的研究主题。
    topic: Annotated[str, Field(max_length=500, min_length=1)]
    # 面向用户的说明。
    description: Annotated[str, Field(max_length=5000, min_length=1)]
    # 检索时间范围的开始日期。
    start_date: date
    # 检索时间范围的结束日期。
    end_date: date
    # 用户指定的会议或期刊。
    venues: Annotated[list[str], Field(max_length=100)] = Field(default_factory=list)
    # 会议期刊质量要求。
    venue_quality: VenueQualityRequirement | None = None
    # 用户要求包含的关键词。
    keywords: list[str]
    # 用户要求排除的关键词。
    exclusion_keywords: list[str] | None = None
    # 允许返回的最大论文数量。
    max_results: Annotated[int, Field(ge=1, le=1000)]
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_date_range(self) -> "SearchRequest":
        """校验输入和业务约束。"""
        if self.start_date > self.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        return self


class PaperSearchResult(BaseModel):
    """表示一次处理结果。"""
    # 数据来源。
    source: str
    # 数据来源中的唯一标识。
    source_id: str
    # 论文或资源标题。
    title: str
    # 论文作者列表。
    authors: list[str] = Field(default_factory=list)
    # 论文发表年份。
    publication_year: int | None = None
    # 论文发表日期。
    publication_date: date | None = None
    # 论文发表类型。
    publication_type: str | None = None
    # 论文发表的会议或期刊。
    venue: str | None = None
    # 论文 DOI。
    doi: str | None = None
    # 论文摘要。
    abstract: str | None = None
    # 论文落地页地址。
    landing_page_url: str | None = None
    # 可下载的论文 PDF 地址。
    pdf_url: str | None = None
    # 论文是否可以开放获取。
    is_open_access: bool = False
    # 论文的开放获取状态。
    open_access_status: str | None = None
    # 论文被引用次数。
    cited_by_count: int = 0


class SourceSearchMetric(BaseModel):
    """一次文献来源调用的结构化可观测性数据。"""

    # 数据来源。
    source: Annotated[str, Field(min_length=1)]
    # 本次调用使用的查询词。
    query: Annotated[str, Field(min_length=1)]
    # 操作耗时，单位为毫秒。
    duration_ms: Annotated[float, Field(ge=0)]
    # 本次调用返回的结果数量。
    result_count: Annotated[int, Field(ge=0)]
    # 本次调用的结果状态。
    outcome: SourceSearchOutcome
    # 失败异常的类型名称。
    error_type: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_success(cls, data: Any) -> Any:
        """Convert metrics persisted before ``outcome`` was introduced."""
        if not isinstance(data, dict):
            return data

        if "outcome" in data or "success" not in data:
            return data

        migrated = data.copy()
        success = migrated.pop("success")
        migrated["outcome"] = (
            SourceSearchOutcome.SUCCESS
            if success
            else SourceSearchOutcome.FAILED
        )
        return migrated


class SearchResponse(BaseModel):
    """表示一次响应结果。"""
    # 返回的结果列表。
    results: list[PaperSearchResult] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 各文献来源的调用指标。
    source_metrics: list[SourceSearchMetric] = Field(default_factory=list)


class LiteratureBundle(BaseModel):
    """Literature Agent 对外输出的稳定数据契约。"""

    # 本次处理的输入请求。
    request: SearchRequest
    # 本次实际使用的检索词。
    search_queries: list[str] = Field(default_factory=list)
    # 等待筛选的候选列表。
    candidates: list[PaperSearchResult] = Field(default_factory=list)
    # 筛选或确认后的论文列表。
    selected_papers: list[PaperSearchResult] = Field(default_factory=list)
    # 论文相关性评估列表。
    relevance_assessments: list[PaperRelevanceAssessment] = Field(
        default_factory=list
    )
    # 已经持久化的论文列表。
    persisted_papers: list[Paper] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 各文献来源的调用指标。
    source_metrics: list[SourceSearchMetric] = Field(default_factory=list)
    # 本次运行提取的方法画像列表。
    method_profiles: list[PaperMethodProfile] = Field(default_factory=list)
    # 各阶段模型调用指标。
    llm_metrics: list[LlmCallMetric] = Field(default_factory=list)


class LiteratureAgentState(TypedDict):
    """Literature Agent 子图内部使用的可持久化 JSON 状态。"""

    # 本次处理的输入请求。
    request: dict[str, Any]

    # 本次实际使用的检索词。
    search_queries: NotRequired[list[str]]
    # 等待筛选的候选列表。
    candidates: NotRequired[list[dict[str, Any]]]
    # 筛选或确认后的论文列表。
    selected_papers: NotRequired[list[dict[str, Any]]]
    # 论文相关性评估列表。
    relevance_assessments: NotRequired[list[dict[str, Any]]]
    # 已经持久化的论文列表。
    persisted_papers: NotRequired[list[dict[str, Any]]]
    # 不阻断流程的警告列表。
    warnings: NotRequired[list[str]]
    # 各文献来源的调用指标。
    source_metrics: NotRequired[list[dict[str, Any]]]
    # 失败时的错误信息。
    error: NotRequired[str]
    # 本次运行提取的方法画像列表。
    method_profiles: NotRequired[list[dict[str, Any]]]
    # 各阶段模型调用指标。
    llm_metrics: NotRequired[list[dict[str, Any]]]
