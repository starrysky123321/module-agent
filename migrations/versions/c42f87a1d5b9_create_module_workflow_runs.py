"""create module workflow runs

Revision ID: c42f87a1d5b9
Revises: ab31d9e742c0
Create Date: 2026-09-27

"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c42f87a1d5b9"
down_revision: str | None = "ab31d9e742c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_workflow_runs",
        sa.Column("literature_run_id", sa.BigInteger(), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "deadline_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "cancellation_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["literature_run_id"],
            ["literature_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("literature_run_id"),
        sa.UniqueConstraint("trace_id"),
    )
    op.create_index(
        op.f("ix_module_workflow_runs_deadline_at"),
        "module_workflow_runs",
        ["deadline_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_module_workflow_runs_status"),
        "module_workflow_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_module_workflow_runs_trace_id"),
        "module_workflow_runs",
        ["trace_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_module_workflow_runs_trace_id"),
        table_name="module_workflow_runs",
    )
    op.drop_index(
        op.f("ix_module_workflow_runs_status"),
        table_name="module_workflow_runs",
    )
    op.drop_index(
        op.f("ix_module_workflow_runs_deadline_at"),
        table_name="module_workflow_runs",
    )
    op.drop_table("module_workflow_runs")
