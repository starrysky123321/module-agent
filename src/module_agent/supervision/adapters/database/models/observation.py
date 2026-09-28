from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from module_agent.shared.database.base import Base


class SupervisorFailureObservationModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "supervisor_failure_observations"

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
    # 发生失败的工作流阶段。
    failure_step: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    # 失败所属的类别。
    failure_category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    # 失败原因说明。
    failure_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    # 该失败是否允许重试。
    failure_retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    # 失败发生时的执行次数。
    failure_attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    # 触发失败的异常类型。
    failure_error_type: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    # 规则策略给出的处置结果。
    rule_disposition: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    # Jev 给出的处置建议。
    jev_disposition: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )
    # 当前结果的可信度。
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    # 建议重试的概率。
    retry_probability: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    # 建议停止的概率。
    stop_probability: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    # 调用的模型名称。
    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    # 当前 HTTP 请求 ID。
    request_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    # 外部建议调用耗时，单位为毫秒。
    latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    # Jev 建议是否与规则决策一致。
    agrees: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        index=True,
    )
    # 建议是否达到可信门槛。
    meets_confidence_threshold: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
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
        index=True,
    )
