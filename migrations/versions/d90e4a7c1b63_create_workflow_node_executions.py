"""create workflow node executions

Revision ID: d90e4a7c1b63
Revises: c42f87a1d5b9
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d90e4a7c1b63"
down_revision: str | None = "c42f87a1d5b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_node_executions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "literature_run_id",
            sa.BigInteger(),
            sa.ForeignKey("literature_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("node", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("input_summary", postgresql.JSONB(), nullable=False),
        sa.Column("output_summary", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_workflow_node_executions_workflow_created",
        "workflow_node_executions",
        ["literature_run_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_node_executions_trace_id",
        "workflow_node_executions",
        ["trace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_node_executions_trace_id",
        table_name="workflow_node_executions",
    )
    op.drop_index(
        "ix_workflow_node_executions_workflow_created",
        table_name="workflow_node_executions",
    )
    op.drop_table("workflow_node_executions")
