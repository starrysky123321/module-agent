"""Expand venue ranking level for ICORE status values.

Revision ID: b7c4e907cdd1
Revises: 8667ab2560ac
Create Date: 2026-08-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7c4e907cdd1"
down_revision: Union[str, Sequence[str], None] = "8667ab2560ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "venue_rankings",
        "level",
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "venue_rankings",
        "level",
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
