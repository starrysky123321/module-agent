from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Date,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import date
from module_agent.shared.database.base import Base
from sqlalchemy.sql import text
from module_agent.venue_catalog.adapters.database.models import VenueModel

class PaperModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_paper_source_source_id"),
        Index(
            "uq_papers_doi",
            "doi",
            unique=True,
            postgresql_where=text("doi IS NOT NULL"),
        )
    )

    # 记录主键。
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 数据来源。
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    # 数据来源中的唯一标识。
    source_id: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    # 论文或资源标题。
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    # 论文作者列表。
    authors: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    # 论文发表年份。
    publication_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    # 论文发表日期。
    publication_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    # 论文发表类型。
    publication_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    # 关联的会议或期刊 ID。
    venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("venues.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 论文发表的会议或期刊。
    venue: Mapped[VenueModel | None] = relationship()
    # 会议或期刊名称。
    venue_name: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    # 论文 DOI。
    doi: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    # 论文摘要。
    abstract: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # 论文落地页地址。
    landing_page_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # 可下载的论文 PDF 地址。
    pdf_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # 论文的开放获取状态。
    open_access_status: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    # 论文是否可以开放获取。
    is_open_access: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    # 论文被引用次数。
    cited_by_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    # Code Agent 判断的代码公开与许可状态。
    code_availability: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    # Code Agent 确认的最佳仓库地址。
    code_repository_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # 最佳仓库置信度。
    code_repository_confidence: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    # 支撑仓库判断的结构化证据。
    code_repository_evidence: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
