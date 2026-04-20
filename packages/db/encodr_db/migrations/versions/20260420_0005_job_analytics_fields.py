"""Add small job analytics fields for storage and failure reporting."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_0005"
down_revision = "20260420_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("failure_category", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("input_size_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("output_size_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("space_saved_bytes", sa.BigInteger(), nullable=True))
        batch_op.create_index("ix_jobs_failure_category", ["failure_category"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_index("ix_jobs_failure_category")
        batch_op.drop_column("space_saved_bytes")
        batch_op.drop_column("output_size_bytes")
        batch_op.drop_column("input_size_bytes")
        batch_op.drop_column("failure_category")
