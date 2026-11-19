from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from module_agent.shared.database.base import Base


class LiteratureJobOutboxModel(Base):
    __tablename__ = "literature_job_outbox"
    __table_args__ = (
        Index(
            "ix_literature_job_outbox_pending",
            "available_at",
            "message_id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("literature_runs.id", ondelete="CASCADE"), unique=True
    )
    resume_workflow: Mapped[bool] = mapped_column()
    trace_id: Mapped[UUID | None] = mapped_column(Uuid)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LiteratureJobInboxModel(Base):
    __tablename__ = "literature_job_inbox"

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("literature_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
