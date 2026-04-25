"""Add persisted telemetry aggregations."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from encodr_db.models.base import json_type


revision = "20260425_0016"
down_revision = "20260423_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_aggregations",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("measurable_job_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("measurable_completed_job_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_original_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_output_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_space_saved_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("completed_space_saved_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_audio_tracks_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_subtitle_tracks_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("savings_by_action", json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("telemetry_aggregations")
