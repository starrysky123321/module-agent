"""Persist outbound literature jobs and inbound processing receipts."""

from alembic import op
import sqlalchemy as sa

revision = "93b74deba104"
down_revision = "e204b7d831fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "literature_job_outbox",
        sa.Column("message_id", sa.String(255), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("literature_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("resume_workflow", sa.Boolean(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_literature_job_outbox_pending",
        "literature_job_outbox",
        ["available_at", "message_id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "literature_job_inbox",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("literature_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("message_id", sa.String(255), primary_key=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("literature_job_inbox")
    op.drop_table("literature_job_outbox")
