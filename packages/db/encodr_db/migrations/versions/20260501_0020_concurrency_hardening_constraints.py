"""Add concurrency hardening constraints."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260501_0020"
down_revision = "20260430_0019"
branch_labels = None
depends_on = None


BOOTSTRAP_ADMIN_INDEX_NAME = "uq_users_single_bootstrap_admin"
BULK_QUEUE_ACTIVE_INDEX_NAME = "uq_bulk_queue_operations_one_active"
ACTIVE_BULK_QUEUE_WHERE = "status IN ('pending', 'running', 'cancelling')"


def upgrade() -> None:
    bind = op.get_bind()
    bootstrap_duplicates = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) AS bootstrap_count
            FROM users
            WHERE is_bootstrap_admin IS TRUE
            """
        )
    ).scalar_one()
    if int(bootstrap_duplicates or 0) > 1:
        raise RuntimeError(
            "Cannot add single bootstrap-admin uniqueness while multiple bootstrap admins exist."
        )

    active_bulk_count = bind.execute(
        sa.text(
            f"""
            SELECT COUNT(*) AS active_count
            FROM bulk_queue_operations
            WHERE {ACTIVE_BULK_QUEUE_WHERE}
            """
        )
    ).scalar_one()
    if int(active_bulk_count or 0) > 1:
        raise RuntimeError(
            "Cannot add bulk queue singleton uniqueness while multiple active bulk operations exist."
        )

    op.create_index(
        BOOTSTRAP_ADMIN_INDEX_NAME,
        "users",
        ["is_bootstrap_admin"],
        unique=True,
        postgresql_where=sa.text("is_bootstrap_admin IS TRUE"),
        sqlite_where=sa.text("is_bootstrap_admin = 1"),
    )

    dialect_name = op.get_context().dialect.name
    if dialect_name == "postgresql":
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX {BULK_QUEUE_ACTIVE_INDEX_NAME} "
                f"ON bulk_queue_operations ((1)) WHERE {ACTIVE_BULK_QUEUE_WHERE}"
            )
        )
    elif dialect_name == "sqlite":
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX {BULK_QUEUE_ACTIVE_INDEX_NAME} "
                f"ON bulk_queue_operations (1) WHERE {ACTIVE_BULK_QUEUE_WHERE}"
            )
        )
    else:
        raise RuntimeError(
            f"Unsupported database dialect for {BULK_QUEUE_ACTIVE_INDEX_NAME}: {dialect_name}"
        )


def downgrade() -> None:
    op.drop_index(BULK_QUEUE_ACTIVE_INDEX_NAME, table_name="bulk_queue_operations")
    op.drop_index(BOOTSTRAP_ADMIN_INDEX_NAME, table_name="users")
