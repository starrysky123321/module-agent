from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from module_agent.shared.database.base import Base


class ModuleWorkflowRunModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "module_workflow_runs"

    # 关联的文献任务 ID。
    literature_run_id: Mapped[int] = mapped_column(
        ForeignKey("literature_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 跨服务追踪 ID。
    trace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
    )
    # 当前处理状态。
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )
    # 任务截止时间。
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    # 用户请求取消的时间。
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # 记录创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # 记录更新时间。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # 任务结束时间。
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # 失败时的错误信息。
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
