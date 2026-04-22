"""Add scan persistence, watched jobs, scheduling, and interruption fields."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260423_0013"
down_revision = "20260422_0012"
branch_labels = None
depends_on = None


def drop_jobs_status_check_constraints() -> None:
    if op.get_context().dialect.name == "sqlite":
        return

    bind = op.get_bind()
    constraint_names = bind.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint AS c
            JOIN pg_class AS t ON t.oid = c.conrelid
            WHERE t.relname = 'jobs'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) ILIKE '%status%'
            """
        )
    ).scalars()

    for constraint_name in constraint_names:
        op.execute(sa.text(f'ALTER TABLE jobs DROP CONSTRAINT IF EXISTS "{constraint_name}"'))


def upgrade() -> None:
    op.create_table(
        "watched_job_definitions",
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("media_class", sa.String(length=32), nullable=False, server_default="movie"),
        sa.Column("ruleset_override", sa.String(length=32), nullable=True),
        sa.Column("preferred_worker_id", sa.String(), nullable=True),
        sa.Column("pinned_worker_id", sa.String(), nullable=True),
        sa.Column("preferred_backend", sa.String(length=64), nullable=True),
        sa.Column("schedule_windows", sa.JSON(), nullable=True),
        sa.Column("auto_queue", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("stage_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_scan_record_id", sa.String(), nullable=True),
        sa.Column("last_seen_paths", sa.JSON(), nullable=True),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_enqueue_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["pinned_worker_id"], ["workers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["preferred_worker_id"], ["workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watched_job_definitions")),
        sa.UniqueConstraint("source_path", name=op.f("uq_watched_job_definitions_source_path")),
    )
    op.create_index(op.f("ix_watched_job_definitions_enabled"), "watched_job_definitions", ["enabled"], unique=False)
    op.create_index(op.f("ix_watched_job_definitions_source_path"), "watched_job_definitions", ["source_path"], unique=False)

    op.create_table(
        "scan_records",
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("watched_job_id", sa.String(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("directory_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("direct_directory_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("video_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likely_show_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likely_season_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likely_episode_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likely_film_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["watched_job_id"], ["watched_job_definitions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_records")),
    )
    op.create_index(op.f("ix_scan_records_scanned_at"), "scan_records", ["scanned_at"], unique=False)
    op.create_index(op.f("ix_scan_records_source_path"), "scan_records", ["source_path"], unique=False)
    op.create_index(op.f("ix_scan_records_watched_job_id"), "scan_records", ["watched_job_id"], unique=False)

    with op.batch_alter_table("watched_job_definitions") as batch_op:
        batch_op.create_foreign_key(
            op.f("fk_watched_job_definitions_last_scan_record_id_scan_records"),
            "scan_records",
            ["last_scan_record_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(sa.Column("schedule_windows", sa.JSON(), nullable=True))

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("preferred_worker_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("pinned_worker_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("watched_job_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("preferred_backend_override", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("schedule_windows", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("schedule_summary", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("scheduled_for_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("interrupted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("interruption_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("interruption_retryable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.create_index("ix_jobs_preferred_worker_id", ["preferred_worker_id"], unique=False)
        batch_op.create_index("ix_jobs_pinned_worker_id", ["pinned_worker_id"], unique=False)
        batch_op.create_index("ix_jobs_watched_job_id", ["watched_job_id"], unique=False)
        batch_op.create_index("ix_jobs_preferred_backend_override", ["preferred_backend_override"], unique=False)
        batch_op.create_index("ix_jobs_scheduled_for_at", ["scheduled_for_at"], unique=False)
        batch_op.create_index("ix_jobs_interrupted_at", ["interrupted_at"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_jobs_preferred_worker_id_workers"),
            "workers",
            ["preferred_worker_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_jobs_pinned_worker_id_workers"),
            "workers",
            ["pinned_worker_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_jobs_watched_job_id_watched_job_definitions"),
            "watched_job_definitions",
            ["watched_job_id"],
            ["id"],
            ondelete="SET NULL",
        )

    new_options = (
        "pending",
        "scheduled",
        "running",
        "completed",
        "failed",
        "interrupted",
        "skipped",
        "manual_review",
    )
    drop_jobs_status_check_constraints()
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=32))
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.Enum(*new_options, name="job_status", native_enum=False, create_constraint=True),
            existing_nullable=False,
        )
    


def downgrade() -> None:
    drop_jobs_status_check_constraints()
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=32))
        batch_op.drop_constraint(op.f("fk_jobs_watched_job_id_watched_job_definitions"), type_="foreignkey")
        batch_op.drop_constraint(op.f("fk_jobs_pinned_worker_id_workers"), type_="foreignkey")
        batch_op.drop_constraint(op.f("fk_jobs_preferred_worker_id_workers"), type_="foreignkey")
        batch_op.drop_index("ix_jobs_interrupted_at")
        batch_op.drop_index("ix_jobs_scheduled_for_at")
        batch_op.drop_index("ix_jobs_preferred_backend_override")
        batch_op.drop_index("ix_jobs_watched_job_id")
        batch_op.drop_index("ix_jobs_pinned_worker_id")
        batch_op.drop_index("ix_jobs_preferred_worker_id")
        batch_op.drop_column("interruption_retryable")
        batch_op.drop_column("interruption_reason")
        batch_op.drop_column("interrupted_at")
        batch_op.drop_column("scheduled_for_at")
        batch_op.drop_column("schedule_summary")
        batch_op.drop_column("schedule_windows")
        batch_op.drop_column("preferred_backend_override")
        batch_op.drop_column("watched_job_id")
        batch_op.drop_column("pinned_worker_id")
        batch_op.drop_column("preferred_worker_id")
    old_options = ("pending", "running", "completed", "failed", "skipped", "manual_review")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.Enum(*old_options, name="job_status", native_enum=False, create_constraint=True),
            existing_nullable=False,
        )
    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_column("schedule_windows")

    with op.batch_alter_table("watched_job_definitions") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_watched_job_definitions_last_scan_record_id_scan_records"),
            type_="foreignkey",
        )
    op.drop_index(op.f("ix_watched_job_definitions_source_path"), table_name="watched_job_definitions")
    op.drop_index(op.f("ix_watched_job_definitions_enabled"), table_name="watched_job_definitions")
    op.drop_table("watched_job_definitions")

    op.drop_index(op.f("ix_scan_records_watched_job_id"), table_name="scan_records")
    op.drop_index(op.f("ix_scan_records_source_path"), table_name="scan_records")
    op.drop_index(op.f("ix_scan_records_scanned_at"), table_name="scan_records")
    op.drop_table("scan_records")
