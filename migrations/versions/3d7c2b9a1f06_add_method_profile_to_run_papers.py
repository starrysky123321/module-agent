"""add method profile to literature run papers

Revision ID: 3d7c2b9a1f06
Revises: f4a61c3d9b20
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "3d7c2b9a1f06"
down_revision: str | None = "f4a61c3d9b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "literature_run_papers",
        sa.Column(
            "method_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("literature_run_papers", "method_profile")
