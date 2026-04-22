"""Add per-worker preferences and pairing fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_0012"
down_revision = "20260422_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(
            sa.Column("preferred_backend", sa.String(length=64), nullable=False, server_default="cpu_only")
        )
        batch_op.add_column(
            sa.Column("allow_cpu_fallback", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(sa.Column("pairing_token_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("pairing_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("pairing_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("onboarding_platform", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_workers_pairing_token_hash", ["pairing_token_hash"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_index("ix_workers_pairing_token_hash")
        batch_op.drop_column("onboarding_platform")
        batch_op.drop_column("pairing_expires_at")
        batch_op.drop_column("pairing_requested_at")
        batch_op.drop_column("pairing_token_hash")
        batch_op.drop_column("allow_cpu_fallback")
        batch_op.drop_column("preferred_backend")
