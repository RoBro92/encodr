"""Rebuild telemetry removed-track counts."""

from __future__ import annotations

from alembic import op


revision = "20260506_0022"
down_revision = "20260501_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM telemetry_aggregations")


def downgrade() -> None:
    pass
