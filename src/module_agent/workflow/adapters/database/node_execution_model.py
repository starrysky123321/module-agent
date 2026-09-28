from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from module_agent.shared.database.base import Base


class WorkflowNodeExecutionModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "workflow_node_executions"
    __table_args__ = (
        Index(
            "ix_workflow_node_executions_workflow_created",
            "literature_run_id",
            "created_at",
        ),
        Index("ix_workflow_node_executions_trace_id", "trace_id"),
    )

    # 记录主键。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 关联的文献任务 ID。
    literature_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("literature_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 跨服务追踪 ID。
    trace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    # LangGraph 节点名称。
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    # 当前执行次数。
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    # 当前处理状态。
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # 操作耗时，单位为毫秒。
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    # 节点输入的脱敏摘要。
    input_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    # 节点输出的脱敏摘要。
    output_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    # 失败时的错误信息。
    error: Mapped[str | None] = mapped_column(String(1000))
    # 记录创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
