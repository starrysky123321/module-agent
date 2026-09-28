from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from module_agent.shared.database.base import Base


class CodeRunModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "code_runs"
    __table_args__ = (
        UniqueConstraint(
            "literature_run_id",
            "attempt",
            name="uq_code_run_execution",
        ),
        CheckConstraint("attempt >= 1", name="ck_code_run_attempt"),
    )

    # 记录主键。
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 关联的文献任务 ID。
    literature_run_id: Mapped[int] = mapped_column(
        ForeignKey("literature_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 当前执行次数。
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    # 跨服务追踪 ID。
    trace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    # 当前处理状态。
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    # 本次处理的输入请求。
    request: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    # 失败时的错误信息。
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 记录创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # 任务开始时间。
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # 任务结束时间。
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # 等待处理的代码产物。
    artifacts: Mapped[list[CodeRunArtifactModel]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CodeRunArtifactModel.position",
    )


class CodeRunArtifactModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "code_run_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "code_run_id",
            "position",
            name="uq_code_run_artifact_position",
        ),
    )

    # 关联的 CodeRun ID。
    code_run_id: Mapped[int] = mapped_column(
        ForeignKey("code_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 关联的论文 ID。
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 论文在本次推荐中的顺序。
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # 本次执行生成的代码产物。
    artifact: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )

    # 所属的任务运行记录。
    run: Mapped[CodeRunModel] = relationship(back_populates="artifacts")
