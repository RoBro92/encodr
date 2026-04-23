"""Add per-worker storage/runtime fields and dry-run job fields."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260423_0014"
down_revision = "20260423_0013"
branch_labels = None
depends_on = None


JOB_KIND_ENUM = sa.Enum(
    "execution",
    "dry_run",
    name="job_kind",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("path_mappings", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("scratch_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("install_dir", sa.Text(), nullable=True))

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "job_kind",
                JOB_KIND_ENUM,
                nullable=False,
                server_default="execution",
            )
        )
        batch_op.create_index("ix_jobs_job_kind", ["job_kind"], unique=False)
        batch_op.add_column(sa.Column("analysis_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("analysis_payload")
        batch_op.drop_index("ix_jobs_job_kind")
        batch_op.drop_column("job_kind")

    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_column("install_dir")
        batch_op.drop_column("scratch_path")
        batch_op.drop_column("path_mappings")
        batch_op.drop_column("max_concurrent_jobs")
