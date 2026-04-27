"""Add queue clearing, cancellation, and backup policy job fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0017"
down_revision = "20260425_0016"
branch_labels = None
depends_on = None


NEW_JOB_STATUS_OPTIONS = (
    "pending",
    "scheduled",
    "running",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
    "skipped",
    "manual_review",
)

OLD_JOB_STATUS_OPTIONS = (
    "pending",
    "scheduled",
    "running",
    "completed",
    "failed",
    "interrupted",
    "skipped",
    "manual_review",
)


def drop_jobs_status_check_constraints() -> None:
    if op.get_context().dialect.name == "sqlite":
        return

    bind = op.get_bind()
    constraint_names = bind.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint AS c
            JOIN pg_class AS t ON t.oid = c.conrelid
            WHERE t.relname = 'jobs'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) ILIKE '%status%'
            """
        )
    ).scalars()

    for constraint_name in constraint_names:
        op.execute(sa.text(f'ALTER TABLE jobs DROP CONSTRAINT IF EXISTS "{constraint_name}"'))


def upgrade() -> None:
    drop_jobs_status_check_constraints()
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=32))
        batch_op.add_column(sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cleared_reason", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancellation_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "backup_policy",
                sa.String(length=64),
                nullable=False,
                server_default="keep",
            )
        )
        batch_op.add_column(sa.Column("backup_retention_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("backup_deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("backup_restored_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_jobs_cleared_at", ["cleared_at"])
        batch_op.create_index("ix_jobs_cleared_reason", ["cleared_reason"])
        batch_op.create_index("ix_jobs_cancellation_requested_at", ["cancellation_requested_at"])
        batch_op.create_index("ix_jobs_backup_retention_until", ["backup_retention_until"])

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.Enum(*NEW_JOB_STATUS_OPTIONS, name="job_status", native_enum=False, create_constraint=True),
            existing_nullable=False,
        )


def downgrade() -> None:
    drop_jobs_status_check_constraints()
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=32))

    op.execute("UPDATE jobs SET status = 'interrupted' WHERE status = 'cancelled'")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.Enum(*OLD_JOB_STATUS_OPTIONS, name="job_status", native_enum=False, create_constraint=True),
            existing_nullable=False,
        )
        batch_op.drop_index("ix_jobs_backup_retention_until")
        batch_op.drop_index("ix_jobs_cancellation_requested_at")
        batch_op.drop_index("ix_jobs_cleared_reason")
        batch_op.drop_index("ix_jobs_cleared_at")
        batch_op.drop_column("backup_restored_at")
        batch_op.drop_column("backup_deleted_at")
        batch_op.drop_column("backup_retention_until")
        batch_op.drop_column("backup_policy")
        batch_op.drop_column("cancellation_reason")
        batch_op.drop_column("cancellation_requested_at")
        batch_op.drop_column("cleared_reason")
        batch_op.drop_column("cleared_at")
