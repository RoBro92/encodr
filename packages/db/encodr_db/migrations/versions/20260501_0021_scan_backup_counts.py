"""Persist backup counts on scan records."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260501_0021"
down_revision = "20260501_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scan_records") as batch_op:
        batch_op.add_column(sa.Column("backup_file_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("backup_files_payload", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("scan_records") as batch_op:
        batch_op.drop_column("backup_files_payload")
        batch_op.drop_column("backup_file_count")
