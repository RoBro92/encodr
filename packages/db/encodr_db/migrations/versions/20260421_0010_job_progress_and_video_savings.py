"""Add job progress and video savings fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_0010"
down_revision = "20260420_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("progress_stage", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("progress_percent", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("progress_out_time_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("progress_fps", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("progress_speed", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("video_input_size_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("video_output_size_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("video_space_saved_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("non_video_space_saved_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("compression_reduction_percent", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("compression_reduction_percent")
        batch_op.drop_column("non_video_space_saved_bytes")
        batch_op.drop_column("video_space_saved_bytes")
        batch_op.drop_column("video_output_size_bytes")
        batch_op.drop_column("video_input_size_bytes")
        batch_op.drop_column("progress_updated_at")
        batch_op.drop_column("progress_speed")
        batch_op.drop_column("progress_fps")
        batch_op.drop_column("progress_out_time_seconds")
        batch_op.drop_column("progress_percent")
        batch_op.drop_column("progress_stage")
