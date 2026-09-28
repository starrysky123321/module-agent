"""create supervisor failure observations

Revision ID: 7fb1c8d4a2e6
Revises: 1594c04479a1
Create Date: 2026-09-27

"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "7fb1c8d4a2e6"
down_revision: str | None = "1594c04479a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supervisor_failure_observations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("literature_run_id", sa.BigInteger(), nullable=False),
        sa.Column("failure_step", sa.String(length=50), nullable=False),
        sa.Column("failure_category", sa.String(length=50), nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=False),
        sa.Column("failure_retryable", sa.Boolean(), nullable=False),
        sa.Column("failure_attempt", sa.Integer(), nullable=False),
        sa.Column("failure_error_type", sa.String(length=200), nullable=True),
        sa.Column("rule_disposition", sa.String(length=20), nullable=False),
        sa.Column("jev_disposition", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("retry_probability", sa.Float(), nullable=True),
        sa.Column("stop_probability", sa.Float(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("agrees", sa.Boolean(), nullable=True),
        sa.Column(
            "meets_confidence_threshold",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["literature_run_id"],
            ["literature_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_supervisor_failure_observations_agrees"),
        "supervisor_failure_observations",
        ["agrees"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supervisor_failure_observations_created_at"),
        "supervisor_failure_observations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supervisor_failure_observations_failure_category"),
        "supervisor_failure_observations",
        ["failure_category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supervisor_failure_observations_failure_step"),
        "supervisor_failure_observations",
        ["failure_step"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supervisor_failure_observations_jev_disposition"),
        "supervisor_failure_observations",
        ["jev_disposition"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supervisor_failure_observations_literature_run_id"),
        "supervisor_failure_observations",
        ["literature_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supervisor_failure_observations_rule_disposition"),
        "supervisor_failure_observations",
        ["rule_disposition"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_supervisor_failure_observations_rule_disposition"),
        table_name="supervisor_failure_observations",
    )
    op.drop_index(
        op.f("ix_supervisor_failure_observations_literature_run_id"),
        table_name="supervisor_failure_observations",
    )
    op.drop_index(
        op.f("ix_supervisor_failure_observations_jev_disposition"),
        table_name="supervisor_failure_observations",
    )
    op.drop_index(
        op.f("ix_supervisor_failure_observations_failure_step"),
        table_name="supervisor_failure_observations",
    )
    op.drop_index(
        op.f("ix_supervisor_failure_observations_failure_category"),
        table_name="supervisor_failure_observations",
    )
    op.drop_index(
        op.f("ix_supervisor_failure_observations_created_at"),
        table_name="supervisor_failure_observations",
    )
    op.drop_index(
        op.f("ix_supervisor_failure_observations_agrees"),
        table_name="supervisor_failure_observations",
    )
    op.drop_table("supervisor_failure_observations")
