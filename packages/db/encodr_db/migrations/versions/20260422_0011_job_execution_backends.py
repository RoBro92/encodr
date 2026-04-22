"""Add job execution backend fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_0011"
down_revision = "20260421_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("requested_execution_backend", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("actual_execution_backend", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("actual_execution_accelerator", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("backend_fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("backend_selection_reason", sa.Text(), nullable=True))
        batch_op.create_index("ix_jobs_requested_execution_backend", ["requested_execution_backend"], unique=False)
        batch_op.create_index("ix_jobs_actual_execution_backend", ["actual_execution_backend"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_index("ix_jobs_actual_execution_backend")
        batch_op.drop_index("ix_jobs_requested_execution_backend")
        batch_op.drop_column("backend_selection_reason")
        batch_op.drop_column("backend_fallback_used")
        batch_op.drop_column("actual_execution_accelerator")
        batch_op.drop_column("actual_execution_backend")
        batch_op.drop_column("requested_execution_backend")
