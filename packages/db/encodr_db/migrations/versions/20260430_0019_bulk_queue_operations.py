"""Add bulk queue operation progress tracking."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from encodr_db.models.base import json_type


revision = "20260430_0019"
down_revision = "20260429_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bulk_queue_operations",
        sa.Column("selection_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status_text", sa.Text(), nullable=True),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("total_expected", sa.Integer(), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("queued_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("current_batch", sa.Integer(), nullable=False),
        sa.Column("total_batches", sa.Integer(), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("result_summary", json_type(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bulk_queue_operations")),
    )
    op.create_index(
        "ix_bulk_queue_operations_selection_hash",
        "bulk_queue_operations",
        ["selection_hash"],
        unique=False,
    )
    op.create_index(
        "ix_bulk_queue_operations_status_updated_at",
        "bulk_queue_operations",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bulk_queue_operations_status_updated_at", table_name="bulk_queue_operations")
    op.drop_index("ix_bulk_queue_operations_selection_hash", table_name="bulk_queue_operations")
    op.drop_table("bulk_queue_operations")
