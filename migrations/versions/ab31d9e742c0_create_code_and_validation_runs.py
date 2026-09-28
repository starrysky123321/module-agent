"""create code and validation runs

Revision ID: ab31d9e742c0
Revises: 7fb1c8d4a2e6
Create Date: 2026-09-27

"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ab31d9e742c0"
down_revision: str | None = "7fb1c8d4a2e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "code_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("literature_run_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "request",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt >= 1", name="ck_code_run_attempt"),
        sa.ForeignKeyConstraint(
            ["literature_run_id"],
            ["literature_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "literature_run_id",
            "attempt",
            name="uq_code_run_execution",
        ),
    )
    op.create_index(
        op.f("ix_code_runs_literature_run_id"),
        "code_runs",
        ["literature_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_runs_status"),
        "code_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_runs_trace_id"),
        "code_runs",
        ["trace_id"],
        unique=False,
    )
    op.create_table(
        "code_run_artifacts",
        sa.Column("code_run_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "artifact",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["code_run_id"],
            ["code_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("code_run_id", "paper_id"),
        sa.UniqueConstraint(
            "code_run_id",
            "position",
            name="uq_code_run_artifact_position",
        ),
    )
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("literature_run_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "request",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt >= 1",
            name="ck_validation_run_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["literature_run_id"],
            ["literature_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "literature_run_id",
            "attempt",
            name="uq_validation_run_execution",
        ),
    )
    op.create_index(
        op.f("ix_validation_runs_literature_run_id"),
        "validation_runs",
        ["literature_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_validation_runs_status"),
        "validation_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_validation_runs_trace_id"),
        "validation_runs",
        ["trace_id"],
        unique=False,
    )
    op.create_table(
        "validation_run_reports",
        sa.Column("validation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["validation_run_id"],
            ["validation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("validation_run_id", "paper_id"),
        sa.UniqueConstraint(
            "validation_run_id",
            "position",
            name="uq_validation_run_report_position",
        ),
    )


def downgrade() -> None:
    op.drop_table("validation_run_reports")
    op.drop_index(
        op.f("ix_validation_runs_trace_id"),
        table_name="validation_runs",
    )
    op.drop_index(
        op.f("ix_validation_runs_status"),
        table_name="validation_runs",
    )
    op.drop_index(
        op.f("ix_validation_runs_literature_run_id"),
        table_name="validation_runs",
    )
    op.drop_table("validation_runs")
    op.drop_table("code_run_artifacts")
    op.drop_index(
        op.f("ix_code_runs_trace_id"),
        table_name="code_runs",
    )
    op.drop_index(
        op.f("ix_code_runs_status"),
        table_name="code_runs",
    )
    op.drop_index(
        op.f("ix_code_runs_literature_run_id"),
        table_name="code_runs",
    )
    op.drop_table("code_runs")
