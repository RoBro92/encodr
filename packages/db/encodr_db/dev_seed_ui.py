from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from encodr_core.config.base import OutputContainer
from encodr_core.media import (
    AudioStream,
    ContainerFormat,
    MediaFile,
    StreamDisposition,
    StreamTags,
    SubtitleKind,
    SubtitleStream,
    VideoStream,
)
from encodr_core.planning import (
    AudioSelectionIntent,
    ConfidenceLevel,
    ContainerHandling,
    ContainerPlan,
    PlanAction,
    PlanReason,
    PlanSummary,
    PlanWarning,
    PolicyContext,
    ProcessingPlan,
    RenamePlan,
    RenameTemplateSource,
    ReplacePlan,
    SelectedStreamSet,
    SubtitleSelectionIntent,
    VideoHandling,
    VideoPlan,
    build_dry_run_analysis_payload,
)
from encodr_db.models import (
    ComplianceState,
    FileLifecycleState,
    Job,
    JobKind,
    JobStatus,
    PlanSnapshot,
    ProbeSnapshot,
    ReplacementStatus,
    TrackedFile,
    VerificationStatus,
    Worker,
    WorkerHealthStatus,
    WorkerRegistrationStatus,
    WorkerType,
)
from encodr_db.repositories import WorkerRepository
from encodr_shared.scheduling import schedule_windows_summary

DEMO_SEED_MARKER = "encodr-ui-demo-v1"
DEMO_MEDIA_ROOT = "/media/__encodr_ui_demo__"
DEMO_WORKER_DISPLAY_NAME = "Demo Local CPU Worker"
_WORKER_MARKER_KEY = "_encodr_ui_demo_seed"
_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class UiDemoSeedSummary:
    worker_id: str
    worker_key: str
    worker_display_name: str
    tracked_files_seeded: int
    jobs_seeded: int
    review_items_seeded: int
    demo_media_root: str = DEMO_MEDIA_ROOT


@dataclass(frozen=True, slots=True)
class UiDemoClearSummary:
    tracked_files_removed: int
    jobs_removed: int
    review_items_removed: int
    worker_removed: bool
    worker_restored: bool
    demo_media_root: str = DEMO_MEDIA_ROOT


@dataclass(frozen=True, slots=True)
class _SeedTarget:
    tracked_file: TrackedFile
    probe_snapshot: ProbeSnapshot
    plan_snapshot: PlanSnapshot
    media_file: MediaFile
    plan: ProcessingPlan


def seed_ui_demo_data(session_factory: sessionmaker, config_bundle: Any) -> UiDemoSeedSummary:
    """Replace and seed local UI demo data for layout/design work."""
    with session_factory() as session:
        _clear_demo_data(session, config_bundle)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        worker = _seed_local_cpu_worker(session, config_bundle, now=now)
        targets = _seed_targets_and_jobs(session, worker=worker, now=now)
        session.commit()
        return UiDemoSeedSummary(
            worker_id=worker.id,
            worker_key=worker.worker_key,
            worker_display_name=worker.display_name,
            tracked_files_seeded=targets["tracked_files"],
            jobs_seeded=targets["jobs"],
            review_items_seeded=targets["review_items"],
        )


def clear_ui_demo_data(session_factory: sessionmaker, config_bundle: Any) -> UiDemoClearSummary:
    """Remove demo records and restore any local worker settings replaced by the seed."""
    with session_factory() as session:
        summary = _clear_demo_data(session, config_bundle)
        session.commit()
        return summary


def _clear_demo_data(session: Session, config_bundle: Any) -> UiDemoClearSummary:
    demo_files = list(
        session.scalars(
            select(TrackedFile).where(
                or_(
                    TrackedFile.source_path.startswith(f"{DEMO_MEDIA_ROOT}/"),
                    TrackedFile.fingerprint_placeholder.startswith(f"{DEMO_SEED_MARKER}:"),
                )
            )
        )
    )
    jobs_removed = sum(len(item.jobs) for item in demo_files)
    review_items_removed = sum(1 for item in demo_files if _is_review_item(item))

    for tracked_file in demo_files:
        session.delete(tracked_file)
    session.flush()

    worker_removed = False
    worker_restored = False
    worker_key = _local_worker_key(config_bundle)
    worker = WorkerRepository(session).get_local_worker(worker_key)
    if worker is not None and _is_demo_seeded_worker(worker):
        previous_worker = _worker_seed_marker(worker).get("previous_local_worker")
        if previous_worker:
            _restore_worker(worker, previous_worker)
            worker_restored = True
        else:
            session.delete(worker)
            worker_removed = True
        session.flush()

    return UiDemoClearSummary(
        tracked_files_removed=len(demo_files),
        jobs_removed=jobs_removed,
        review_items_removed=review_items_removed,
        worker_removed=worker_removed,
        worker_restored=worker_restored,
    )


def _seed_local_cpu_worker(session: Session, config_bundle: Any, *, now: datetime) -> Worker:
    repository = WorkerRepository(session)
    worker_key = _local_worker_key(config_bundle)
    existing_worker = repository.get_local_worker(worker_key)
    previous_snapshot = _snapshot_worker(existing_worker) if existing_worker is not None else None
    scratch_path = _local_scratch_path(config_bundle)
    media_mounts = _local_media_mounts(config_bundle)
    schedule_windows = [
        {
            "days": ["mon", "tue", "wed", "thu", "fri"],
            "start_time": "18:00",
            "end_time": "23:59",
        }
    ]
    worker = repository.upsert_local_worker(
        worker_key=worker_key,
        display_name=DEMO_WORKER_DISPLAY_NAME,
        enabled=True,
        preferred_backend="cpu_only",
        allow_cpu_fallback=True,
        max_concurrent_jobs=1,
        schedule_windows=schedule_windows,
        path_mappings=None,
        scratch_path=scratch_path,
        host_metadata={
            "hostname": _local_host(config_bundle),
            "platform": "linux",
            "agent_version": "ui-demo",
            "python_version": "3.12",
            _WORKER_MARKER_KEY: {
                "marker": DEMO_SEED_MARKER,
                "created_at": now.isoformat(),
                "previous_local_worker": previous_snapshot,
            },
        },
    )
    worker.capability_payload = {
        "execution_modes": ["remux", "transcode"],
        "supported_video_codecs": ["h264", "hevc", "av1"],
        "supported_audio_codecs": ["aac", "ac3", "eac3", "opus"],
        "hardware_hints": ["cpu_only"],
        "binary_support": {"ffmpeg": True, "ffprobe": True},
        "max_concurrent_jobs": 1,
        "recommended_concurrency": 1,
        "recommended_concurrency_reason": "Demo CPU worker is capped at one concurrent job.",
        "tags": ["local", "demo"],
    }
    worker.runtime_payload = {
        "queue": _local_queue(config_bundle),
        "scratch_dir": scratch_path,
        "scratch_status": {
            "path": scratch_path,
            "status": "healthy",
            "message": "Demo scratch path is ready.",
        },
        "media_mounts": media_mounts,
        "path_mappings": [],
        "preferred_backend": "cpu_only",
        "allow_cpu_fallback": True,
        "max_concurrent_jobs": 1,
        "schedule_windows": schedule_windows,
        "telemetry": _demo_telemetry(),
        "demo_seed": DEMO_SEED_MARKER,
    }
    worker.binary_payload = {
        "binaries": [
            {
                "name": "ffmpeg",
                "configured_path": "/usr/bin/ffmpeg",
                "discoverable": True,
                "message": "Demo binary status: available.",
            },
            {
                "name": "ffprobe",
                "configured_path": "/usr/bin/ffprobe",
                "discoverable": True,
                "message": "Demo binary status: available.",
            },
        ]
    }
    worker.last_seen_at = now
    worker.last_heartbeat_at = now
    worker.last_registration_at = now
    worker.last_health_status = WorkerHealthStatus.HEALTHY
    worker.last_health_summary = "Demo local CPU worker is healthy and available."
    session.flush()
    return worker


def _seed_targets_and_jobs(session: Session, *, worker: Worker, now: datetime) -> dict[str, int]:
    running = _create_target(
        session,
        slug="running-transcode",
        source_path=f"{DEMO_MEDIA_ROOT}/Movies/Arc Light (2023)/Arc Light (2023).mkv",
        size_bytes=42 * _GIB,
        duration_seconds=7460.0,
        is_4k=False,
        lifecycle_state=FileLifecycleState.PROCESSING,
        compliance_state=ComplianceState.NON_COMPLIANT,
        action=PlanAction.TRANSCODE,
        confidence=ConfidenceLevel.HIGH,
        reasons=[
            _reason("video_codec_policy", "Source video is H.264 and the Movies profile targets HEVC."),
            _reason("audio_language_policy", "English audio is retained while commentary tracks are removed."),
        ],
        warnings=[
            _warning("estimated_runtime", "CPU transcode is expected to take several hours."),
        ],
        selected_audio_indices=[1],
        dropped_audio_indices=[2, 3],
        selected_subtitle_indices=[4],
        dropped_subtitle_indices=[5],
        created_at=now - timedelta(minutes=36),
    )
    running_job = _create_job(
        session,
        target=running,
        worker=worker,
        job_kind=JobKind.EXECUTION,
        status=JobStatus.RUNNING,
        created_at=now - timedelta(minutes=35),
        updated_at=now - timedelta(seconds=18),
        started_at=now - timedelta(minutes=32),
        requested_backend="cpu",
        actual_backend="cpu",
        progress_stage="encoding",
        progress_percent=63,
        progress_out_time_seconds=4700,
        progress_fps=34.7,
        progress_speed=0.74,
        progress_updated_at=now - timedelta(seconds=18),
        output_path="/temp/encodr/Arc Light (2023).encodr.mkv",
        execution_command=[
            "ffmpeg",
            "-i",
            running.tracked_file.source_path,
            "-c:v",
            "libx265",
            "-preset",
            "medium",
            "/temp/encodr/Arc Light (2023).encodr.mkv",
        ],
    )

    scheduled = _create_target(
        session,
        slug="scheduled-dry-run",
        source_path=f"{DEMO_MEDIA_ROOT}/TV/Signal Harbor/Season 01/Signal Harbor - S01E04 - Night Shift.mkv",
        size_bytes=7 * _GIB,
        duration_seconds=2710.0,
        is_4k=False,
        lifecycle_state=FileLifecycleState.QUEUED,
        compliance_state=ComplianceState.NON_COMPLIANT,
        action=PlanAction.TRANSCODE,
        confidence=ConfidenceLevel.MEDIUM,
        reasons=[
            _reason("dry_run_requested", "Operator requested an analysis-only pass before queueing execution."),
            _reason("subtitle_cleanup", "One full English subtitle track would be retained."),
        ],
        warnings=[
            _warning("schedule_window", "The dry run is waiting for its permitted schedule window."),
        ],
        selected_audio_indices=[1, 2],
        dropped_audio_indices=[3],
        selected_subtitle_indices=[4],
        dropped_subtitle_indices=[5],
        created_at=now - timedelta(minutes=24),
    )
    schedule_windows = [
        {
            "days": ["mon", "tue", "wed", "thu", "fri"],
            "start_time": "23:00",
            "end_time": "06:00",
        }
    ]
    dry_run_payload = build_dry_run_analysis_payload(scheduled.media_file, scheduled.plan)
    _create_job(
        session,
        target=scheduled,
        worker=worker,
        job_kind=JobKind.DRY_RUN,
        status=JobStatus.SCHEDULED,
        created_at=now - timedelta(minutes=23),
        updated_at=now - timedelta(minutes=20),
        scheduled_for_at=now + timedelta(hours=2, minutes=15),
        requested_backend="cpu",
        actual_backend=None,
        schedule_windows=schedule_windows,
        analysis_payload=dry_run_payload,
    )

    failed = _create_target(
        session,
        slug="failed-interrupted",
        source_path=f"{DEMO_MEDIA_ROOT}/Movies/The Long Archive (1998)/The Long Archive (1998) - Director's Cut.mkv",
        size_bytes=19 * _GIB,
        duration_seconds=6890.0,
        is_4k=False,
        lifecycle_state=FileLifecycleState.FAILED,
        compliance_state=ComplianceState.NON_COMPLIANT,
        action=PlanAction.TRANSCODE,
        confidence=ConfidenceLevel.MEDIUM,
        reasons=[
            _reason("legacy_codec", "Source video uses MPEG-2 and should be transcoded."),
            _reason("retry_candidate", "The failure is retryable after scratch space is checked."),
        ],
        warnings=[
            _warning("partial_output_removed", "A partial output was removed after the worker interruption."),
        ],
        selected_audio_indices=[1],
        dropped_audio_indices=[2],
        selected_subtitle_indices=[4],
        dropped_subtitle_indices=[],
        created_at=now - timedelta(hours=1, minutes=20),
    )
    failed_job = _create_job(
        session,
        target=failed,
        worker=worker,
        job_kind=JobKind.EXECUTION,
        status=JobStatus.INTERRUPTED,
        created_at=now - timedelta(hours=1, minutes=18),
        updated_at=now - timedelta(minutes=48),
        started_at=now - timedelta(hours=1, minutes=15),
        completed_at=now - timedelta(minutes=48),
        interrupted_at=now - timedelta(minutes=49),
        requested_backend="cpu",
        actual_backend="cpu",
        progress_stage="interrupted",
        progress_percent=41,
        progress_out_time_seconds=2820,
        progress_fps=28.1,
        progress_speed=0.62,
        progress_updated_at=now - timedelta(minutes=49),
        attempt_count=2,
        failure_message="Worker process was interrupted while writing the verification sample. Retry is safe after confirming scratch space.",
        failure_category="worker_interrupted",
        interruption_reason="Worker process lost its encoder child process during output verification.",
        interruption_retryable=True,
        output_path="/temp/encodr/The Long Archive (1998) - Director's Cut.encodr.partial.mkv",
        execution_stderr="frame=28410 fps=28 q=27.0 size=7391MiB time=00:47:00 bitrate=21461.5kbits/s\nencodr: worker process interrupted before verification completed",
    )

    _create_target(
        session,
        slug="compression-safety-review",
        source_path=f"{DEMO_MEDIA_ROOT}/Movies/Glass City (2021)/Glass City (2021).mkv",
        size_bytes=12 * _GIB,
        duration_seconds=6040.0,
        is_4k=False,
        lifecycle_state=FileLifecycleState.MANUAL_REVIEW,
        compliance_state=ComplianceState.MANUAL_REVIEW,
        action=PlanAction.MANUAL_REVIEW,
        confidence=ConfidenceLevel.LOW,
        reasons=[
            _reason("manual_review_compression_safety", "Projected video reduction is 67%, above the safety threshold."),
        ],
        warnings=[
            _warning("quality_risk", "Compression could remove visible grain from a dark, high-motion source."),
        ],
        selected_audio_indices=[1],
        dropped_audio_indices=[2],
        selected_subtitle_indices=[4],
        dropped_subtitle_indices=[5],
        video_max_reduction_percent=45,
        created_at=now - timedelta(minutes=16),
    )

    _create_target(
        session,
        slug="protected-4k-review",
        source_path=f"{DEMO_MEDIA_ROOT}/Movies/Northern Skies (2019)/Northern Skies (2019) - 2160p HDR.mkv",
        size_bytes=61 * _GIB,
        duration_seconds=7320.0,
        is_4k=True,
        lifecycle_state=FileLifecycleState.MANUAL_REVIEW,
        compliance_state=ComplianceState.MANUAL_REVIEW,
        action=PlanAction.MANUAL_REVIEW,
        confidence=ConfidenceLevel.HIGH,
        reasons=[
            _reason("protected_4k_preserve", "4K/HDR source matches the protected preserve rule."),
            _reason("planner_protected", "Planner marked this file as protected from automated replacement."),
        ],
        warnings=[
            _warning("manual_approval_required", "Operator approval is required before any replacement job can be created."),
        ],
        selected_audio_indices=[1, 2],
        dropped_audio_indices=[],
        selected_subtitle_indices=[4],
        dropped_subtitle_indices=[],
        protected=True,
        should_treat_as_protected=True,
        transcode_required=False,
        target_codec=None,
        video_handling=VideoHandling.PRESERVE,
        created_at=now - timedelta(minutes=12),
    )

    _create_target(
        session,
        slug="unknown-language-audio-review",
        source_path=f"{DEMO_MEDIA_ROOT}/TV/Midnight Train/Season 02/Midnight Train - S02E07 - Static Lines.mkv",
        size_bytes=5 * _GIB,
        duration_seconds=2980.0,
        is_4k=False,
        lifecycle_state=FileLifecycleState.MANUAL_REVIEW,
        compliance_state=ComplianceState.MANUAL_REVIEW,
        action=PlanAction.MANUAL_REVIEW,
        confidence=ConfidenceLevel.LOW,
        reasons=[
            _reason("manual_review_unknown_language_audio", "Primary audio language is marked und and cannot be matched to preferences."),
            _reason("audio_selection_uncertain", "Multiple commentary-like tracks have missing language tags."),
        ],
        warnings=[
            _warning("subtitle_language_unknown", "One subtitle stream is also tagged as und."),
        ],
        selected_audio_indices=[1],
        dropped_audio_indices=[2, 3],
        selected_subtitle_indices=[4],
        dropped_subtitle_indices=[5],
        created_at=now - timedelta(minutes=8),
        audio_languages=["und", "eng", "jpn"],
        subtitle_languages=["eng", "und"],
    )

    worker.runtime_payload = {
        **(worker.runtime_payload or {}),
        "current_job_id": running_job.id,
        "current_backend": "cpu",
        "current_stage": "encoding",
        "current_progress_percent": 63,
        "current_progress_updated_at": (now - timedelta(seconds=18)).isoformat(),
        "last_completed_job_id": failed_job.id,
    }
    session.flush()
    return {
        "tracked_files": 6,
        "jobs": 3,
        "review_items": 3,
    }


def _create_target(
    session: Session,
    *,
    slug: str,
    source_path: str,
    size_bytes: int,
    duration_seconds: float,
    is_4k: bool,
    lifecycle_state: FileLifecycleState,
    compliance_state: ComplianceState,
    action: PlanAction,
    confidence: ConfidenceLevel,
    reasons: list[PlanReason],
    warnings: list[PlanWarning],
    selected_audio_indices: list[int],
    dropped_audio_indices: list[int],
    selected_subtitle_indices: list[int],
    dropped_subtitle_indices: list[int],
    created_at: datetime,
    protected: bool = False,
    should_treat_as_protected: bool = False,
    operator_protected: bool = False,
    transcode_required: bool = True,
    target_codec: str | None = "hevc",
    video_handling: VideoHandling = VideoHandling.TRANSCODE_TO_POLICY,
    video_max_reduction_percent: int = 55,
    audio_languages: list[str] | None = None,
    subtitle_languages: list[str] | None = None,
) -> _SeedTarget:
    media_file = _build_media_file(
        source_path=source_path,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
        is_4k=is_4k,
        audio_languages=audio_languages or ["eng", "eng", "jpn"],
        subtitle_languages=subtitle_languages or ["eng", "spa"],
    )
    selected_streams = SelectedStreamSet(
        video_stream_indices=[0],
        audio_stream_indices=selected_audio_indices,
        subtitle_stream_indices=selected_subtitle_indices,
    )
    plan = ProcessingPlan(
        action=action,
        summary=PlanSummary(
            action=action,
            confidence=confidence,
            is_already_compliant=False,
            should_treat_as_protected=should_treat_as_protected,
        ),
        policy_context=PolicyContext(
            policy_name="Encodr UI demo policy",
            policy_version=1,
            selected_profile_name="movies_4k" if is_4k else "movies",
            selected_profile_description="Seeded UI demo profile.",
            matched_path_prefix=DEMO_MEDIA_ROOT,
            source_path=Path(source_path),
        ),
        selected_streams=selected_streams,
        audio=AudioSelectionIntent(
            selected_stream_indices=selected_audio_indices,
            dropped_stream_indices=dropped_audio_indices,
            primary_stream_index=selected_audio_indices[0] if selected_audio_indices else None,
            available_preferred_language_stream_indices=[
                index
                for index in selected_audio_indices
                if index not in dropped_audio_indices
            ],
            missing_required_audio=any(language == "und" for language in (audio_languages or [])),
        ),
        subtitles=SubtitleSelectionIntent(
            selected_stream_indices=selected_subtitle_indices,
            dropped_stream_indices=dropped_subtitle_indices,
            forced_stream_indices=[],
            main_stream_index=selected_subtitle_indices[0] if selected_subtitle_indices else None,
            ambiguous_forced_stream_indices=[
                index
                for index, language in enumerate(subtitle_languages or [], start=4)
                if language == "und"
            ],
        ),
        video=VideoPlan(
            primary_stream_index=0,
            handling=video_handling,
            preserve_original=not transcode_required,
            target_codec=target_codec,
            transcode_required=transcode_required,
            quality_mode="balanced" if transcode_required else None,
            max_allowed_video_reduction_percent=video_max_reduction_percent if transcode_required else None,
        ),
        container=ContainerPlan(
            source_extension=Path(source_path).suffix.lower().lstrip(".") or None,
            target_container=OutputContainer.MKV,
            handling=ContainerHandling.PRESERVE,
            change_required=False,
        ),
        rename=RenamePlan(
            enabled=False,
            template_source=RenameTemplateSource.DISABLED,
        ),
        replace=ReplacePlan(
            in_place=True,
            require_verification=True,
            keep_original_until_verified=True,
            delete_replaced_source=False,
        ),
        reasons=reasons,
        warnings=warnings,
        confidence=confidence,
        is_already_compliant=False,
        should_treat_as_protected=should_treat_as_protected,
    )
    source = Path(source_path)
    tracked_file = TrackedFile(
        source_path=source.as_posix(),
        source_filename=source.name,
        source_extension=source.suffix.lower().lstrip(".") or None,
        source_directory=source.parent.as_posix(),
        last_observed_size=size_bytes,
        last_observed_modified_time=created_at - timedelta(days=3),
        fingerprint_placeholder=f"{DEMO_SEED_MARKER}:{slug}",
        is_4k=is_4k,
        lifecycle_state=lifecycle_state,
        compliance_state=compliance_state,
        is_protected=protected or should_treat_as_protected or operator_protected,
        operator_protected=operator_protected,
        operator_protected_note="Seeded demo protection marker." if operator_protected else None,
        operator_protected_updated_at=created_at if operator_protected else None,
        last_processed_policy_version=1,
        last_processed_profile_name="movies_4k" if is_4k else "movies",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(tracked_file)
    session.flush()

    probe_snapshot = ProbeSnapshot(
        tracked_file_id=tracked_file.id,
        schema_version=1,
        payload=media_file.model_dump(mode="json"),
        created_at=created_at + timedelta(seconds=10),
        updated_at=created_at + timedelta(seconds=10),
    )
    session.add(probe_snapshot)
    session.flush()

    plan_snapshot = PlanSnapshot(
        tracked_file_id=tracked_file.id,
        probe_snapshot_id=probe_snapshot.id,
        action=plan.action,
        confidence=plan.confidence,
        policy_version=plan.policy_context.policy_version,
        profile_name=plan.policy_context.selected_profile_name,
        is_already_compliant=plan.is_already_compliant,
        should_treat_as_protected=plan.should_treat_as_protected,
        reasons=[item.model_dump(mode="json") for item in plan.reasons],
        warnings=[item.model_dump(mode="json") for item in plan.warnings],
        selected_streams=plan.selected_streams.model_dump(mode="json"),
        payload=plan.model_dump(mode="json"),
        created_at=created_at + timedelta(seconds=20),
        updated_at=created_at + timedelta(seconds=20),
    )
    session.add(plan_snapshot)
    session.flush()
    return _SeedTarget(
        tracked_file=tracked_file,
        probe_snapshot=probe_snapshot,
        plan_snapshot=plan_snapshot,
        media_file=media_file,
        plan=plan,
    )


def _create_job(
    session: Session,
    *,
    target: _SeedTarget,
    worker: Worker,
    job_kind: JobKind,
    status: JobStatus,
    created_at: datetime,
    updated_at: datetime,
    requested_backend: str | None,
    actual_backend: str | None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    scheduled_for_at: datetime | None = None,
    interrupted_at: datetime | None = None,
    progress_stage: str | None = None,
    progress_percent: int | None = None,
    progress_out_time_seconds: int | None = None,
    progress_fps: float | None = None,
    progress_speed: float | None = None,
    progress_updated_at: datetime | None = None,
    attempt_count: int = 1,
    failure_message: str | None = None,
    failure_category: str | None = None,
    interruption_reason: str | None = None,
    interruption_retryable: bool = True,
    schedule_windows: list[dict] | None = None,
    analysis_payload: dict | None = None,
    output_path: str | None = None,
    execution_command: list[str] | None = None,
    execution_stderr: str | None = None,
) -> Job:
    job = Job(
        tracked_file_id=target.tracked_file.id,
        plan_snapshot_id=target.plan_snapshot.id,
        assigned_worker_id=worker.id if status == JobStatus.RUNNING else None,
        preferred_worker_id=worker.id,
        pinned_worker_id=worker.id,
        last_worker_id=worker.id if status in {JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.RUNNING} else None,
        requested_worker_type=WorkerType.LOCAL,
        job_kind=job_kind,
        preferred_backend_override="cpu_only",
        schedule_windows=schedule_windows,
        schedule_summary=schedule_windows_summary(schedule_windows),
        worker_name=worker.display_name,
        status=status,
        attempt_count=attempt_count,
        started_at=started_at,
        completed_at=completed_at,
        progress_stage=progress_stage,
        progress_percent=progress_percent,
        progress_out_time_seconds=progress_out_time_seconds,
        progress_fps=progress_fps,
        progress_speed=progress_speed,
        progress_updated_at=progress_updated_at,
        scheduled_for_at=scheduled_for_at,
        interrupted_at=interrupted_at,
        interruption_reason=interruption_reason,
        interruption_retryable=interruption_retryable,
        requested_execution_backend=requested_backend,
        actual_execution_backend=actual_backend,
        actual_execution_accelerator=None,
        backend_fallback_used=False,
        backend_selection_reason="Demo worker is configured for CPU-only execution.",
        failure_message=failure_message,
        failure_category=failure_category,
        input_size_bytes=target.tracked_file.last_observed_size,
        output_size_bytes=analysis_payload.get("estimated_output_size_bytes") if analysis_payload else None,
        space_saved_bytes=analysis_payload.get("estimated_space_saved_bytes") if analysis_payload else None,
        analysis_payload=analysis_payload,
        output_path=output_path,
        execution_command=execution_command,
        execution_stderr=execution_stderr,
        verification_status=VerificationStatus.PENDING,
        replacement_status=ReplacementStatus.PENDING,
        replace_in_place=True,
        require_verification=True,
        keep_original_until_verified=True,
        delete_replaced_source=False,
        created_at=created_at,
        updated_at=updated_at,
    )
    session.add(job)
    session.flush()
    return job


def _build_media_file(
    *,
    source_path: str,
    size_bytes: int,
    duration_seconds: float,
    is_4k: bool,
    audio_languages: list[str],
    subtitle_languages: list[str],
) -> MediaFile:
    width = 3840 if is_4k else 1920
    height = 2160 if is_4k else 1080
    video_bit_rate = 56_000_000 if is_4k else 18_000_000
    audio_streams = [
        AudioStream(
            index=index,
            stream_order=index,
            codec_name="eac3" if index == 1 else "aac",
            codec_long_name="E-AC-3" if index == 1 else "AAC",
            tags=StreamTags(
                language=language,
                title="Main 5.1" if index == 1 else "Commentary" if language == "eng" else "Original stereo",
            ),
            disposition=StreamDisposition(default=index == 1, commentary=index > 1 and language == "eng"),
            channels=6 if index == 1 else 2,
            channel_layout="5.1" if index == 1 else "stereo",
            sample_rate_hz=48_000,
            bit_rate=768_000 if index == 1 else 192_000,
            is_surround_candidate=index == 1,
        )
        for index, language in enumerate(audio_languages, start=1)
    ]
    subtitle_start = 1 + len(audio_streams)
    subtitle_streams = [
        SubtitleStream(
            index=index,
            stream_order=index,
            codec_name="subrip",
            codec_long_name="SubRip subtitle",
            tags=StreamTags(language=language, title="Forced" if offset == 0 else "Full subtitles"),
            disposition=StreamDisposition(forced=offset == 0),
            subtitle_kind=SubtitleKind.TEXT,
            is_forced=offset == 0,
        )
        for offset, (index, language) in enumerate(
            zip(range(subtitle_start, subtitle_start + len(subtitle_languages)), subtitle_languages)
        )
    ]
    path = Path(source_path)
    return MediaFile(
        container=ContainerFormat(
            file_path=path,
            file_name=path.name,
            extension=path.suffix.lower().lstrip(".") or None,
            format_name="matroska,webm",
            format_long_name="Matroska / WebM",
            duration_seconds=duration_seconds,
            bit_rate=int((size_bytes * 8) / duration_seconds),
            size_bytes=size_bytes,
            stream_count=1 + len(audio_streams) + len(subtitle_streams),
            tags={"encoder": "Encodr UI demo seed"},
        ),
        video_streams=[
            VideoStream(
                index=0,
                stream_order=0,
                codec_name="h264",
                codec_long_name="H.264 / AVC",
                profile="High",
                tags=StreamTags(language="und", title="Main video"),
                disposition=StreamDisposition(default=True),
                width=width,
                height=height,
                coded_width=width,
                coded_height=height,
                pixel_format="yuv420p10le" if is_4k else "yuv420p",
                frame_rate=23.976,
                raw_frame_rate="24000/1001",
                average_frame_rate=23.976,
                raw_average_frame_rate="24000/1001",
                bit_rate=video_bit_rate,
                is_4k=is_4k,
            )
        ],
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        is_4k=is_4k,
        is_hdr_candidate=is_4k,
        has_english_audio="eng" in audio_languages,
        has_forced_english_subtitle="eng" in subtitle_languages,
        has_surround_audio=True,
        has_atmos_capable_audio=False,
    )


def _reason(code: str, message: str, **metadata: Any) -> PlanReason:
    return PlanReason(code=code, message=message, metadata=metadata)


def _warning(code: str, message: str, **metadata: Any) -> PlanWarning:
    return PlanWarning(code=code, message=message, metadata=metadata)


def _is_review_item(tracked_file: TrackedFile) -> bool:
    return bool(
        tracked_file.lifecycle_state == FileLifecycleState.MANUAL_REVIEW
        or tracked_file.compliance_state == ComplianceState.MANUAL_REVIEW
        or tracked_file.is_protected
        or any(plan.action == PlanAction.MANUAL_REVIEW for plan in tracked_file.plan_snapshots)
        or any(job.status in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW} for job in tracked_file.jobs)
    )


def _snapshot_worker(worker: Worker | None) -> dict[str, Any] | None:
    if worker is None:
        return None
    return {
        "display_name": worker.display_name,
        "enabled": worker.enabled,
        "registration_status": worker.registration_status.value,
        "preferred_backend": worker.preferred_backend,
        "allow_cpu_fallback": worker.allow_cpu_fallback,
        "max_concurrent_jobs": worker.max_concurrent_jobs,
        "schedule_windows": worker.schedule_windows,
        "path_mappings": worker.path_mappings,
        "scratch_path": worker.scratch_path,
        "host_metadata": worker.host_metadata,
        "capability_payload": worker.capability_payload,
        "runtime_payload": worker.runtime_payload,
        "binary_payload": worker.binary_payload,
        "last_seen_at": _datetime_to_text(worker.last_seen_at),
        "last_heartbeat_at": _datetime_to_text(worker.last_heartbeat_at),
        "last_health_status": worker.last_health_status.value,
        "last_health_summary": worker.last_health_summary,
        "last_registration_at": _datetime_to_text(worker.last_registration_at),
    }


def _restore_worker(worker: Worker, snapshot: dict[str, Any]) -> None:
    worker.display_name = snapshot["display_name"]
    worker.enabled = bool(snapshot["enabled"])
    worker.registration_status = WorkerRegistrationStatus(snapshot["registration_status"])
    worker.preferred_backend = snapshot["preferred_backend"]
    worker.allow_cpu_fallback = bool(snapshot["allow_cpu_fallback"])
    worker.max_concurrent_jobs = int(snapshot["max_concurrent_jobs"])
    worker.schedule_windows = snapshot["schedule_windows"]
    worker.path_mappings = snapshot["path_mappings"]
    worker.scratch_path = snapshot["scratch_path"]
    worker.host_metadata = snapshot["host_metadata"]
    worker.capability_payload = snapshot["capability_payload"]
    worker.runtime_payload = snapshot["runtime_payload"]
    worker.binary_payload = snapshot["binary_payload"]
    worker.last_seen_at = _text_to_datetime(snapshot["last_seen_at"])
    worker.last_heartbeat_at = _text_to_datetime(snapshot["last_heartbeat_at"])
    worker.last_health_status = WorkerHealthStatus(snapshot["last_health_status"])
    worker.last_health_summary = snapshot["last_health_summary"]
    worker.last_registration_at = _text_to_datetime(snapshot["last_registration_at"])


def _is_demo_seeded_worker(worker: Worker) -> bool:
    return _worker_seed_marker(worker).get("marker") == DEMO_SEED_MARKER


def _worker_seed_marker(worker: Worker) -> dict[str, Any]:
    metadata = worker.host_metadata or {}
    marker = metadata.get(_WORKER_MARKER_KEY)
    return marker if isinstance(marker, dict) else {}


def _datetime_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _text_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _local_worker_key(config_bundle: Any) -> str:
    return str(getattr(config_bundle.workers.local, "id", "worker-local"))


def _local_host(config_bundle: Any) -> str:
    return str(getattr(config_bundle.workers.local, "host", "lxc-main"))


def _local_queue(config_bundle: Any) -> str:
    return str(getattr(config_bundle.workers.local, "queue", "local"))


def _local_scratch_path(config_bundle: Any) -> str:
    return str(getattr(config_bundle.workers.local, "scratch_dir", "/temp"))


def _local_media_mounts(config_bundle: Any) -> list[str]:
    mounts = getattr(config_bundle.workers.local, "media_mounts", None) or ["/media"]
    return [str(item) for item in mounts]


def _demo_telemetry() -> dict[str, Any]:
    return {
        "cpu_usage_percent": 72.4,
        "process_cpu_usage_percent": 388.5,
        "memory_usage_percent": 58.1,
        "process_memory_bytes": 1_274_019_840,
        "cpu_temperature_c": 63.2,
        "gpu": {
            "vendor": "CPU only",
            "message": "No GPU selected for this demo worker.",
        },
    }
