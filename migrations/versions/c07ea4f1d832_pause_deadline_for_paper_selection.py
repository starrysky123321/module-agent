"""Pause workflow execution deadlines during human paper selection.

Revision ID: c07ea4f1d832
Revises: b42d8a6e1c30
"""

from alembic import op
import sqlalchemy as sa

revision = "c07ea4f1d832"
down_revision = "b42d8a6e1c30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_workflow_runs", sa.Column(
        "selection_wait_started_at", sa.DateTime(timezone=True), nullable=True,
    ))
    # Old waiting rows have not yet timed out. Their last lifecycle write marks
    # entering selection; preserve it instead of starting a new timeout budget.
    op.execute("""
        UPDATE module_workflow_runs
        SET selection_wait_started_at = updated_at
        WHERE status = 'waiting_for_selection' AND updated_at < deadline_at
    """)


def downgrade() -> None:
    # If rolling back while paused, keep the remaining active budget rather
    # than reviving the old wall-clock deadline in the previous application.
    op.execute("""
        UPDATE module_workflow_runs
        SET deadline_at = deadline_at + GREATEST(now() - selection_wait_started_at, interval '0 seconds')
        WHERE status = 'waiting_for_selection' AND selection_wait_started_at IS NOT NULL
    """)
    op.drop_column("module_workflow_runs", "selection_wait_started_at")
