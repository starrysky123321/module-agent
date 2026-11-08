"""Persist per-run paper integrity evidence; preserve historical unknowns."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d91f76a20b4e"
down_revision = "c07ea4f1d832"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("literature_run_papers", sa.Column("integrity", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("literature_run_papers", "integrity")
