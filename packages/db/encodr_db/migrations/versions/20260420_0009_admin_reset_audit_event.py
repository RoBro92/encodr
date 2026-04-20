"""Extend audit event types for CLI admin reset actions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_0009"
down_revision = "20260420_0008"
branch_labels = None
depends_on = None


OLD_AUDIT_EVENT_TYPE = sa.Enum(
    "bootstrap_admin_created",
    "bootstrap_admin_blocked",
    "login",
    "logout",
    "token_refresh",
    "manual_review_action",
    "worker_registration",
    "worker_heartbeat_auth_failure",
    "worker_state_change",
    name="audit_event_type",
    native_enum=False,
    create_constraint=True,
)

NEW_AUDIT_EVENT_TYPE = sa.Enum(
    "bootstrap_admin_created",
    "bootstrap_admin_blocked",
    "admin_reset",
    "login",
    "logout",
    "token_refresh",
    "manual_review_action",
    "worker_registration",
    "worker_heartbeat_auth_failure",
    "worker_state_change",
    name="audit_event_type",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.alter_column(
            "event_type",
            existing_type=OLD_AUDIT_EVENT_TYPE,
            type_=NEW_AUDIT_EVENT_TYPE,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.alter_column(
            "event_type",
            existing_type=NEW_AUDIT_EVENT_TYPE,
            type_=OLD_AUDIT_EVENT_TYPE,
            existing_nullable=False,
        )
