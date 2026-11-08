"""Durable, explicitly approved M5 pilot jobs and their evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "e204b7d831fa"
down_revision = "d91f76a20b4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("experiment_workers",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("resources", pg.JSONB(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("experiment_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("literature_run_id", sa.BigInteger(), sa.ForeignKey("literature_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paper_id", sa.BigInteger(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("worker_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("proposal", pg.JSONB(), nullable=False),
        sa.Column("consent", pg.JSONB(), nullable=True),
        sa.Column("plan", pg.JSONB(), nullable=True),
        sa.Column("result", pg.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("log_tail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for column in ("literature_run_id", "worker_id", "status"):
        op.create_index(f"ix_experiment_jobs_{column}", "experiment_jobs", [column])
    op.create_index("uq_experiment_active_paper", "experiment_jobs", ["literature_run_id", "paper_id"], unique=True,
                    postgresql_where=sa.text("status IN ('queued','preparing','running','cancelling')"))
    op.create_table("experiment_artifacts",
        sa.Column("job_id", pg.UUID(as_uuid=True), sa.ForeignKey("experiment_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False))


def downgrade() -> None:
    op.drop_table("experiment_artifacts")
    op.drop_table("experiment_jobs")
    op.drop_table("experiment_workers")
