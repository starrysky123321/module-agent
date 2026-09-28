"""add relevance metadata to literature run papers

Revision ID: f4a61c3d9b20
Revises: c83e4c922d41
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f4a61c3d9b20"
down_revision: str | None = "c83e4c922d41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "literature_run_papers",
        sa.Column(
            "relevance_score",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "literature_run_papers",
        sa.Column(
            "relevance_reason",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "literature_run_papers",
        sa.Column(
            "matched_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("literature_run_papers", "matched_terms")
    op.drop_column("literature_run_papers", "relevance_reason")
    op.drop_column("literature_run_papers", "relevance_score")
