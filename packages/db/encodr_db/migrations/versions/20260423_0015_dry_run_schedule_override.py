"""Add per-job worker schedule override support."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260423_0015"
down_revision = "20260423_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "ignore_worker_schedule",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("ignore_worker_schedule")
