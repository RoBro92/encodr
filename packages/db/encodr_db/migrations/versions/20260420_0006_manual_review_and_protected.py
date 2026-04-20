"""Add manual review decisions and operator protection fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_0006"
down_revision = "20260420_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tracked_files") as batch_op:
        batch_op.add_column(sa.Column("operator_protected", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("operator_protected_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("operator_protected_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("operator_protected_by_user_id", sa.String(length=36), nullable=True))
        batch_op.create_index(
            "ix_tracked_files_operator_protected_by_user_id",
            ["operator_protected_by_user_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_tracked_files_operator_protected_by_user_id_users",
            "users",
            ["operator_protected_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "manual_review_decisions",
        sa.Column("tracked_file_id", sa.String(length=36), nullable=False),
        sa.Column("plan_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column(
            "decision_type",
            sa.Enum(
                "approved",
                "rejected",
                "held",
                "mark_protected",
                "clear_protected",
                "replan_requested",
                "job_created",
                name="manual_review_decision_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_snapshot_id"], ["plan_snapshots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tracked_file_id"], ["tracked_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manual_review_decisions")),
    )
    op.create_index(
        "ix_manual_review_decisions_tracked_file_id_created_at",
        "manual_review_decisions",
        ["tracked_file_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_manual_review_decisions_created_by_user_id_created_at",
        "manual_review_decisions",
        ["created_by_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_manual_review_decisions_decision_type_created_at",
        "manual_review_decisions",
        ["decision_type", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_manual_review_decisions_tracked_file_id"),
        "manual_review_decisions",
        ["tracked_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_manual_review_decisions_plan_snapshot_id"),
        "manual_review_decisions",
        ["plan_snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_manual_review_decisions_job_id"),
        "manual_review_decisions",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_manual_review_decisions_created_by_user_id"),
        "manual_review_decisions",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_manual_review_decisions_created_by_user_id"), table_name="manual_review_decisions")
    op.drop_index(op.f("ix_manual_review_decisions_job_id"), table_name="manual_review_decisions")
    op.drop_index(op.f("ix_manual_review_decisions_plan_snapshot_id"), table_name="manual_review_decisions")
    op.drop_index(op.f("ix_manual_review_decisions_tracked_file_id"), table_name="manual_review_decisions")
    op.drop_index("ix_manual_review_decisions_decision_type_created_at", table_name="manual_review_decisions")
    op.drop_index("ix_manual_review_decisions_created_by_user_id_created_at", table_name="manual_review_decisions")
    op.drop_index("ix_manual_review_decisions_tracked_file_id_created_at", table_name="manual_review_decisions")
    op.drop_table("manual_review_decisions")

    with op.batch_alter_table("tracked_files") as batch_op:
        batch_op.drop_constraint("fk_tracked_files_operator_protected_by_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_tracked_files_operator_protected_by_user_id")
        batch_op.drop_column("operator_protected_by_user_id")
        batch_op.drop_column("operator_protected_updated_at")
        batch_op.drop_column("operator_protected_note")
        batch_op.drop_column("operator_protected")
