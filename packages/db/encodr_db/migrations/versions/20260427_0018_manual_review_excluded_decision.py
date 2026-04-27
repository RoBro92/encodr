"""Add excluded manual review decision type."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0018"
down_revision = "20260427_0017"
branch_labels = None
depends_on = None


OLD_OPTIONS = (
    "approved",
    "rejected",
    "held",
    "mark_protected",
    "clear_protected",
    "replan_requested",
    "job_created",
)

NEW_OPTIONS = (*OLD_OPTIONS, "excluded")


def drop_manual_review_decision_check_constraints() -> None:
    if op.get_context().dialect.name == "sqlite":
        return

    bind = op.get_bind()
    constraint_names = bind.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint AS c
            JOIN pg_class AS t ON t.oid = c.conrelid
            WHERE t.relname = 'manual_review_decisions'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) ILIKE '%decision_type%'
            """
        )
    ).scalars()

    for constraint_name in constraint_names:
        op.execute(sa.text(f'ALTER TABLE manual_review_decisions DROP CONSTRAINT IF EXISTS "{constraint_name}"'))


def upgrade() -> None:
    drop_manual_review_decision_check_constraints()
    with op.batch_alter_table("manual_review_decisions") as batch_op:
        batch_op.alter_column(
            "decision_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=32),
            existing_nullable=False,
        )

    with op.batch_alter_table("manual_review_decisions") as batch_op:
        batch_op.alter_column(
            "decision_type",
            existing_type=sa.String(length=32),
            type_=sa.Enum(*NEW_OPTIONS, name="manual_review_decision_type", native_enum=False, create_constraint=True),
            existing_nullable=False,
        )


def downgrade() -> None:
    drop_manual_review_decision_check_constraints()
    with op.batch_alter_table("manual_review_decisions") as batch_op:
        batch_op.alter_column(
            "decision_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=32),
            existing_nullable=False,
        )

    op.execute("UPDATE manual_review_decisions SET decision_type = 'held' WHERE decision_type = 'excluded'")

    with op.batch_alter_table("manual_review_decisions") as batch_op:
        batch_op.alter_column(
            "decision_type",
            existing_type=sa.String(length=32),
            type_=sa.Enum(*OLD_OPTIONS, name="manual_review_decision_type", native_enum=False, create_constraint=True),
            existing_nullable=False,
        )
