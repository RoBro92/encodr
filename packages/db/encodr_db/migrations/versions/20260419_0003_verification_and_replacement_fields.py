"""Add verification and replacement persistence fields for jobs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260419_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.Enum(
                    "pending",
                    "passed",
                    "failed",
                    "not_required",
                    name="verification_status",
                    native_enum=False,
                    create_constraint=True,
                ),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("verification_payload", json_type(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "replacement_status",
                sa.Enum(
                    "pending",
                    "succeeded",
                    "failed",
                    "not_required",
                    name="replacement_status",
                    native_enum=False,
                    create_constraint=True,
                ),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("replacement_payload", json_type(), nullable=True))
        batch_op.add_column(sa.Column("final_output_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("original_backup_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("replacement_failure_message", sa.Text(), nullable=True))

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("verification_status", server_default=None)
        batch_op.alter_column("replacement_status", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("replacement_failure_message")
        batch_op.drop_column("original_backup_path")
        batch_op.drop_column("final_output_path")
        batch_op.drop_column("replacement_payload")
        batch_op.drop_column("replacement_status")
        batch_op.drop_column("verification_payload")
        batch_op.drop_column("verification_status")
