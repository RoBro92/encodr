"""Add active tracked-file job uniqueness."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260429_0018"
down_revision = "20260427_0017"
branch_labels = None
depends_on = None


ACTIVE_JOB_INDEX_NAME = "uq_jobs_one_active_per_tracked_file"
ACTIVE_JOB_WHERE = sa.text("status IN ('pending', 'scheduled', 'running') AND cleared_at IS NULL")


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            """
            SELECT tracked_file_id, COUNT(*) AS active_count
            FROM jobs
            WHERE status IN ('pending', 'scheduled', 'running')
              AND cleared_at IS NULL
            GROUP BY tracked_file_id
            HAVING COUNT(*) > 1
            LIMIT 10
            """
        )
    ).fetchall()
    if duplicates:
        summary = ", ".join(f"{row.tracked_file_id} ({row.active_count})" for row in duplicates)
        raise RuntimeError(
            "Cannot add active job uniqueness while duplicate active jobs exist. "
            f"Resolve duplicate pending/scheduled/running jobs for tracked_file_id values: {summary}"
        )
    op.create_index(
        ACTIVE_JOB_INDEX_NAME,
        "jobs",
        ["tracked_file_id"],
        unique=True,
        postgresql_where=ACTIVE_JOB_WHERE,
        sqlite_where=ACTIVE_JOB_WHERE,
    )


def downgrade() -> None:
    op.drop_index(ACTIVE_JOB_INDEX_NAME, table_name="jobs")
