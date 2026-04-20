"""Add job execution fields and expanded job lifecycle statuses."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260419_0002"
down_revision = "20260419_0001"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


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
        batch_op.add_column(sa.Column("output_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("execution_command", json_type(), nullable=True))
        batch_op.add_column(sa.Column("execution_stdout", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("execution_stderr", sa.Text(), nullable=True))
        batch_op.alter_column("status", existing_type=sa.String(length=13), type_=sa.String(length=32))

    op.execute("UPDATE jobs SET status = 'completed' WHERE status = 'succeeded'")
    op.execute("UPDATE jobs SET status = 'manual_review' WHERE status = 'cancelled'")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "skipped",
                "manual_review",
                name="job_status",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    drop_jobs_status_check_constraints()
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=32))

    op.execute("UPDATE jobs SET status = 'succeeded' WHERE status = 'completed'")
    op.execute("UPDATE jobs SET status = 'cancelled' WHERE status = 'manual_review'")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="job_status",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )
        batch_op.drop_column("execution_stderr")
        batch_op.drop_column("execution_stdout")
        batch_op.drop_column("execution_command")
        batch_op.drop_column("output_path")
