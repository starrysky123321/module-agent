"""remove duplicate workflow trace constraint

Revision ID: b42d8a6e1c30
Revises: a31f9c2e7d40
"""

from alembic import op


revision: str = "b42d8a6e1c30"
down_revision: str | None = "a31f9c2e7d40"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # A unique index already enforces this invariant.  Keeping both the index
    # and PostgreSQL's automatically created unique constraint is redundant
    # and makes Alembic report a permanent schema diff.
    op.drop_constraint(
        "module_workflow_runs_trace_id_key",
        "module_workflow_runs",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "module_workflow_runs_trace_id_key",
        "module_workflow_runs",
        ["trace_id"],
    )
