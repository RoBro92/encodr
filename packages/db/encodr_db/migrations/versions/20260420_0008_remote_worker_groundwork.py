"""Add remote worker groundwork models and job associations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_0008"
down_revision = "20260420_0007"
branch_labels = None
depends_on = None


OLD_AUDIT_EVENT_TYPE = sa.Enum(
    "bootstrap_admin_created",
    "bootstrap_admin_blocked",
    "login",
    "logout",
    "token_refresh",
    "manual_review_action",
    name="audit_event_type",
    native_enum=False,
    create_constraint=True,
)

NEW_AUDIT_EVENT_TYPE = sa.Enum(
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


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("worker_key", sa.String(length=255), nullable=False),
        sa.Column(
            "worker_type",
            sa.Enum("local", "remote", name="worker_type", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "registration_status",
            sa.Enum(
                "registered",
                "disabled",
                "unknown",
                name="worker_registration_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("auth_token_hash", sa.String(length=128), nullable=True),
        sa.Column("host_metadata", sa.JSON(), nullable=True),
        sa.Column("capability_payload", sa.JSON(), nullable=True),
        sa.Column("runtime_payload", sa.JSON(), nullable=True),
        sa.Column("binary_payload", sa.JSON(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_health_status",
            sa.Enum(
                "healthy",
                "degraded",
                "failed",
                "unknown",
                name="worker_health_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_health_summary", sa.Text(), nullable=True),
        sa.Column("last_registration_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workers")),
        sa.UniqueConstraint("worker_key", name=op.f("uq_workers_worker_key")),
    )
    op.create_index("ix_workers_worker_key", "workers", ["worker_key"], unique=True)
    op.create_index("ix_workers_worker_type_enabled", "workers", ["worker_type", "enabled"], unique=False)
    op.create_index("ix_workers_last_seen_at", "workers", ["last_seen_at"], unique=False)
    op.create_index(op.f("ix_workers_auth_token_hash"), "workers", ["auth_token_hash"], unique=False)
    op.create_index(op.f("ix_workers_worker_type"), "workers", ["worker_type"], unique=False)

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("assigned_worker_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("last_worker_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "requested_worker_type",
                sa.Enum("local", "remote", name="worker_type", native_enum=False, create_constraint=True),
                nullable=True,
            )
        )
        batch_op.create_index(op.f("ix_jobs_assigned_worker_id"), ["assigned_worker_id"], unique=False)
        batch_op.create_index(op.f("ix_jobs_last_worker_id"), ["last_worker_id"], unique=False)
        batch_op.create_index(op.f("ix_jobs_requested_worker_type"), ["requested_worker_type"], unique=False)
        batch_op.create_foreign_key(
            "fk_jobs_assigned_worker_id_workers",
            "workers",
            ["assigned_worker_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_jobs_last_worker_id_workers",
            "workers",
            ["last_worker_id"],
            ["id"],
            ondelete="SET NULL",
        )

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

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("fk_jobs_last_worker_id_workers", type_="foreignkey")
        batch_op.drop_constraint("fk_jobs_assigned_worker_id_workers", type_="foreignkey")
        batch_op.drop_index(op.f("ix_jobs_requested_worker_type"))
        batch_op.drop_index(op.f("ix_jobs_last_worker_id"))
        batch_op.drop_index(op.f("ix_jobs_assigned_worker_id"))
        batch_op.drop_column("requested_worker_type")
        batch_op.drop_column("last_worker_id")
        batch_op.drop_column("assigned_worker_id")

    op.drop_index(op.f("ix_workers_worker_type"), table_name="workers")
    op.drop_index(op.f("ix_workers_auth_token_hash"), table_name="workers")
    op.drop_index("ix_workers_last_seen_at", table_name="workers")
    op.drop_index("ix_workers_worker_type_enabled", table_name="workers")
    op.drop_index("ix_workers_worker_key", table_name="workers")
    op.drop_table("workers")
