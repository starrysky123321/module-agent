"""Durable child jobs and bounded evidence; API needs no host/Docker access."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from module_agent.shared.database.base import Base


class ExperimentJobModel(Base):
    __tablename__ = "experiment_jobs"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("uq_experiment_active_paper", "literature_run_id", "paper_id", unique=True,
              postgresql_where=text("status IN ('queued','preparing','running','cancelling')")),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    literature_run_id: Mapped[int] = mapped_column(ForeignKey("literature_runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"))
    worker_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True, default="draft")
    stage: Mapped[str] = mapped_column(String(40), default="awaiting_approval")
    proposal: Mapped[dict] = mapped_column(JSONB)
    consent: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_tail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExperimentWorkerModel(Base):
    __tablename__ = "experiment_workers"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    resources: Mapped[dict] = mapped_column(JSONB)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentArtifactModel(Base):
    __tablename__ = "experiment_artifacts"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("experiment_jobs.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
