from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Float,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.shared.database.base import Base
from module_agent.literature.adapters.database.models.paper import PaperModel


class LiteratureRunModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "literature_runs"

    # 记录主键。
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 当前处理状态。
    status: Mapped[LiteratureRunStatus] = mapped_column(
        SAEnum(
            LiteratureRunStatus,
            name="literature_run_status",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
        default=LiteratureRunStatus.PENDING,
        index=True,
    )
    # 本次处理的输入请求。
    request: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    # 本次实际使用的检索词。
    search_queries: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    # 不阻断流程的警告列表。
    warnings: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    # 各文献来源的调用指标。
    source_metrics: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    # 各阶段模型调用指标。
    llm_metrics: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    # 失败时的错误信息。
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # 记录创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # 任务开始时间。
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # 任务完成时间。
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # 本次运行与论文的关联记录。
    paper_links: Mapped[list[LiteratureRunPaperModel]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="LiteratureRunPaperModel.position",
        passive_deletes=True,
    )


class LiteratureRunPaperModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "literature_run_papers"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "position",
            name="uq_literature_run_paper_position",
        ),
    )

    # 关联的运行记录 ID。
    run_id: Mapped[int] = mapped_column(
        ForeignKey("literature_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 关联的论文 ID。
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 论文在本次推荐中的顺序。
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    # 论文与用户需求的相关性分数。
    relevance_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default=text("0"),
    )
    # 相关性评分的解释。
    relevance_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    # 匹配到的检索词。
    matched_terms: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    # Literature Agent 提取的方法画像。
    method_profile: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )


    # 所属的任务运行记录。
    run: Mapped[LiteratureRunModel] = relationship(back_populates="paper_links")
    # 关联的论文记录。
    paper: Mapped[PaperModel] = relationship()
