"""add LLM call metrics to literature runs

Revision ID: e2a9c6451b7f
Revises: 3d7c2b9a1f06
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e2a9c6451b7f"
down_revision: str | None = "3d7c2b9a1f06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "literature_runs",
        sa.Column(
            "llm_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("literature_runs", "llm_metrics")
