"""add paper code availability

Revision ID: a31f9c2e7d40
Revises: d90e4a7c1b63
Create Date: 2026-09-27
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a31f9c2e7d40"
down_revision: str | None = "d90e4a7c1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column(
            "code_availability",
            sa.String(length=30),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "papers",
        sa.Column("code_repository_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "papers",
        sa.Column("code_repository_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "papers",
        sa.Column(
            "code_repository_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("papers", "code_repository_evidence")
    op.drop_column("papers", "code_repository_confidence")
    op.drop_column("papers", "code_repository_url")
    op.drop_column("papers", "code_availability")
