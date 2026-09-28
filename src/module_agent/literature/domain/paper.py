from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """封装 Paper 相关的数据和行为。"""
    # 记录主键。
    id: int | None = None

    # 数据来源。
    source: str
    # 数据来源中的唯一标识。
    source_id: str

    # 论文或资源标题。
    title: str
    # 论文作者列表。
    authors: list[str]

    # 论文发表年份。
    publication_year: int | None = None
    # 论文发表日期。
    publication_date: date | None = None
    # 论文发表类型。
    publication_type: str | None = None

    # 关联的会议或期刊 ID。
    venue_id: int | None = None
    # 会议或期刊名称。
    venue_name: str | None = None

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
    # Code Agent 判断的代码公开与许可状态；未处理时为 unknown。
    code_availability: Literal[
        "unknown",
        "not_found",
        "source_available",
        "open_source",
    ] = "unknown"
    # Code Agent 确认的最佳仓库地址。
    code_repository_url: str | None = None
    # 最佳仓库与论文对应关系的可信度。
    code_repository_confidence: Annotated[
        float | None,
        Field(ge=0.0, le=1.0),
    ] = None
    # 支撑仓库判断的结构化证据。
    code_repository_evidence: list[dict[str, object]] = Field(
        default_factory=list
    )
