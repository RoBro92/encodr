"""Initial schema for tracked files, snapshots, and jobs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260419_0001"
down_revision = None
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "tracked_files",
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("source_extension", sa.String(length=32), nullable=True),
        sa.Column("source_directory", sa.Text(), nullable=False),
        sa.Column("last_observed_size", sa.BigInteger(), nullable=True),
        sa.Column("last_observed_modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint_placeholder", sa.String(length=255), nullable=True),
        sa.Column("is_4k", sa.Boolean(), nullable=False),
        sa.Column(
            "lifecycle_state",
            sa.Enum(
                "discovered",
                "probed",
                "planned",
                "manual_review",
                "queued",
                "processing",
                "completed",
                "failed",
                name="file_lifecycle_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "compliance_state",
            sa.Enum(
                "unknown",
                "compliant",
                "non_compliant",
                "manual_review",
                name="compliance_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("is_protected", sa.Boolean(), nullable=False),
        sa.Column("last_processed_policy_version", sa.Integer(), nullable=True),
        sa.Column("last_processed_profile_name", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracked_files")),
        sa.UniqueConstraint("source_path", name=op.f("uq_tracked_files_source_path")),
    )
    op.create_index("ix_tracked_files_created_at", "tracked_files", ["created_at"], unique=False)
    op.create_index("ix_tracked_files_updated_at", "tracked_files", ["updated_at"], unique=False)

    op.create_table(
        "probe_snapshots",
        sa.Column("tracked_file_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracked_file_id"],
            ["tracked_files.id"],
            name=op.f("fk_probe_snapshots_tracked_file_id_tracked_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_probe_snapshots")),
    )
    op.create_index(
        "ix_probe_snapshots_tracked_file_id",
        "probe_snapshots",
        ["tracked_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_probe_snapshots_tracked_file_id_created_at",
        "probe_snapshots",
        ["tracked_file_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "plan_snapshots",
        sa.Column("tracked_file_id", sa.String(length=36), nullable=False),
        sa.Column("probe_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "skip",
                "remux",
                "transcode",
                "manual_review",
                name="plan_action",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Enum(
                "high",
                "medium",
                "low",
                name="plan_confidence",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("profile_name", sa.String(length=255), nullable=True),
        sa.Column("is_already_compliant", sa.Boolean(), nullable=False),
        sa.Column("should_treat_as_protected", sa.Boolean(), nullable=False),
        sa.Column("reasons", json_type(), nullable=False),
        sa.Column("warnings", json_type(), nullable=False),
        sa.Column("selected_streams", json_type(), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["probe_snapshot_id"],
            ["probe_snapshots.id"],
            name=op.f("fk_plan_snapshots_probe_snapshot_id_probe_snapshots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_file_id"],
            ["tracked_files.id"],
            name=op.f("fk_plan_snapshots_tracked_file_id_tracked_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_snapshots")),
    )
    op.create_index(
        "ix_plan_snapshots_probe_snapshot_id",
        "plan_snapshots",
        ["probe_snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_plan_snapshots_tracked_file_id",
        "plan_snapshots",
        ["tracked_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_plan_snapshots_tracked_file_id_created_at",
        "plan_snapshots",
        ["tracked_file_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "jobs",
        sa.Column("tracked_file_id", sa.String(length=36), nullable=False),
        sa.Column("plan_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="job_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("replace_in_place", sa.Boolean(), nullable=False),
        sa.Column("require_verification", sa.Boolean(), nullable=False),
        sa.Column("keep_original_until_verified", sa.Boolean(), nullable=False),
        sa.Column("delete_replaced_source", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_snapshot_id"],
            ["plan_snapshots.id"],
            name=op.f("fk_jobs_plan_snapshot_id_plan_snapshots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_file_id"],
            ["tracked_files.id"],
            name=op.f("fk_jobs_tracked_file_id_tracked_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_started_at", "jobs", ["started_at"], unique=False)
    op.create_index("ix_jobs_completed_at", "jobs", ["completed_at"], unique=False)
    op.create_index("ix_jobs_tracked_file_id", "jobs", ["tracked_file_id"], unique=False)
    op.create_index("ix_jobs_plan_snapshot_id", "jobs", ["plan_snapshot_id"], unique=False)
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_index("ix_jobs_plan_snapshot_id", table_name="jobs")
    op.drop_index("ix_jobs_tracked_file_id", table_name="jobs")
    op.drop_index("ix_jobs_completed_at", table_name="jobs")
    op.drop_index("ix_jobs_started_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_plan_snapshots_tracked_file_id_created_at", table_name="plan_snapshots")
    op.drop_index("ix_plan_snapshots_tracked_file_id", table_name="plan_snapshots")
    op.drop_index("ix_plan_snapshots_probe_snapshot_id", table_name="plan_snapshots")
    op.drop_table("plan_snapshots")

    op.drop_index("ix_probe_snapshots_tracked_file_id_created_at", table_name="probe_snapshots")
    op.drop_index("ix_probe_snapshots_tracked_file_id", table_name="probe_snapshots")
    op.drop_table("probe_snapshots")

    op.drop_index("ix_tracked_files_updated_at", table_name="tracked_files")
    op.drop_index("ix_tracked_files_created_at", table_name="tracked_files")
    op.drop_table("tracked_files")
