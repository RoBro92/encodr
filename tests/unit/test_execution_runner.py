from __future__ import annotations

from datetime import datetime, timezone
import errno
import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from encodr_core.config import load_config_bundle
from encodr_core.execution import (
    ExecutionCancelledError,
    ExecutionResult,
    ExecutionRunner,
    FFmpegProcessError,
    build_execution_command_plan,
    build_temp_output_path,
)
from encodr_core.execution.metrics import calculate_media_savings
from encodr_core.media.models import MediaFile
from encodr_core.planning import PlanAction, ProcessingPlan, build_processing_plan
from encodr_core.probe import parse_ffprobe_json_output
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus
from encodr_db import Base
from encodr_db.models import ComplianceState, FileLifecycleState, Job, JobStatus, ReplacementStatus as DbReplacementStatus, VerificationStatus as DbVerificationStatus
from encodr_db.repositories import JobRepository, PlanSnapshotRepository, ProbeSnapshotRepository, TrackedFileRepository
from encodr_db.runtime import LocalWorkerLoop, WorkerExecutionService
import encodr_db.runtime.worker as worker_runtime

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ffprobe"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_skip_job_completes_without_ffmpeg(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = media_at_path(parse_fixture("tv_episode.json"), tmp_path / "Example Show - s01e01 - Pilot.mkv")
        media.file_path.write_text("source", encoding="utf-8")
        job, plan = create_job(session, bundle, media, source_path=media.file_path.as_posix())

        service = WorkerExecutionService(runner=ExecutionRunner(ffmpeg_client=FailIfCalledClient()))
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed = session.get(Job, job.id)
        assert result.status == "skipped"
        assert result.failure_message is None
        assert result.failure_category is None
        assert refreshed.status == JobStatus.SKIPPED
        assert refreshed.failure_message is None
        assert refreshed.failure_category is None
        assert refreshed.verification_status == DbVerificationStatus.NOT_REQUIRED
        assert refreshed.replacement_status == DbReplacementStatus.NOT_REQUIRED


def test_worker_refuses_encodr_backup_target_without_transcoding(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Old Copy.encodr-backup.mkv"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("backup", encoding="utf-8")
        media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())

        service = WorkerExecutionService(runner=ExecutionRunner(ffmpeg_client=FailIfCalledClient()))
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed = session.get(Job, job.id)
        assert result.status == "skipped"
        assert result.failure_category == "excluded_encodr_artifact"
        assert "backup files" in (result.failure_message or "").lower()
        assert refreshed.status == JobStatus.SKIPPED
        assert refreshed.failure_category == "excluded_encodr_artifact"
        assert refreshed.verification_status == DbVerificationStatus.NOT_REQUIRED
        assert refreshed.replacement_status == DbReplacementStatus.NOT_REQUIRED
        assert source_path.exists()


def test_manual_review_job_is_marked_correctly(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = media_at_path(parse_fixture("no_english_audio.json"), tmp_path / "Example Foreign Audio Film.mkv")
        media.file_path.write_text("source", encoding="utf-8")
        job, plan = create_job(session, bundle, media, source_path=media.file_path.as_posix())

        service = WorkerExecutionService(runner=ExecutionRunner(ffmpeg_client=FailIfCalledClient()))
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed = session.get(Job, job.id)
        assert result.status == "manual_review"
        assert refreshed.status == JobStatus.MANUAL_REVIEW
        assert refreshed.verification_status == DbVerificationStatus.NOT_REQUIRED


def test_remux_plan_builds_expected_ffmpeg_command() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("non4k_remux_languages.json")
    plan = build_processing_plan(media, bundle, source_path="/media/Movies/Example Remux Film (2024).mkv")

    command_plan = build_execution_command_plan(
        plan,
        input_path=media.file_path,
        scratch_dir="/scratch/encodr",
        ffmpeg_path="/usr/bin/ffmpeg",
        job_id="job-123",
    )

    assert command_plan.mode == "remux"
    assert command_plan.command[:4] == ["/usr/bin/ffmpeg", "-y", "-i", str(media.file_path)]
    assert "-c:v" in command_plan.command
    assert "copy" in command_plan.command
    assert command_plan.requested_backend == "cpu"
    assert "hardware encoders are not used" in (command_plan.backend_selection_reason or "")
    assert command_plan.output_path == Path("/scratch/encodr/Example Remux Film (2024).job-123.tmp.mkv")


def test_remux_plan_maps_selected_streams_and_sets_explicit_dispositions() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("non4k_remux_languages.json")
    plan = build_processing_plan(media, bundle, source_path="/media/Movies/Example Remux Film (2024).mkv")

    command_plan = build_execution_command_plan(
        plan,
        input_path=media.file_path,
        scratch_dir="/scratch/encodr",
        ffmpeg_path="/usr/bin/ffmpeg",
        job_id="job-maps",
    )

    mapped_inputs = [
        command_plan.command[index + 1]
        for index, value in enumerate(command_plan.command)
        if value == "-map"
    ]
    assert mapped_inputs == ["0:0", "0:1", "0:5", "0:4"]
    assert "0:2" not in mapped_inputs
    assert "0:3" not in mapped_inputs
    assert "0:6" not in mapped_inputs
    assert _option_value(command_plan.command, "-disposition:a:0") == "default"
    assert _option_value(command_plan.command, "-disposition:s:0") == "forced"
    assert _option_value(command_plan.command, "-disposition:s:1") == "default"


def test_transcode_plan_builds_expected_ffmpeg_command() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("film_1080p.json")
    plan = build_processing_plan(media, bundle, source_path="/media/Movies/Example Film (2024).mkv")

    command_plan = build_execution_command_plan(
        plan,
        input_path=media.file_path,
        scratch_dir="/scratch/encodr",
        ffmpeg_path="/usr/bin/ffmpeg",
        job_id="job-456",
    )

    assert command_plan.mode == "transcode"
    assert "-c:v" in command_plan.command
    assert "libx265" in command_plan.command
    assert command_plan.output_path == Path("/scratch/encodr/Example Film (2024).job-456.tmp.mkv")


def test_transcode_plan_maps_selected_streams_only() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("non4k_remux_languages.json")
    media.video_streams[0].codec_name = "h264"
    media.video_streams[0].bit_rate = 20_000_000
    plan = build_processing_plan(media, bundle, source_path="/media/Movies/Example Transcode Strip Film (2024).mkv")

    command_plan = build_execution_command_plan(
        plan,
        input_path=media.file_path,
        scratch_dir="/scratch/encodr",
        ffmpeg_path="/usr/bin/ffmpeg",
        job_id="job-transcode-maps",
    )

    mapped_inputs = [
        command_plan.command[index + 1]
        for index, value in enumerate(command_plan.command)
        if value == "-map"
    ]
    assert command_plan.mode == "transcode"
    assert mapped_inputs == ["0:0", "0:1", "0:5", "0:4"]
    assert "0:2" not in mapped_inputs
    assert "0:3" not in mapped_inputs
    assert "0:6" not in mapped_inputs


def test_transcode_plan_respects_configured_crf_override() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    profile = bundle.profiles["movies-default"]
    assert profile.video is not None
    assert profile.video.non_4k is not None
    profile.video.non_4k.quality_crf = 22
    media = parse_fixture("film_1080p.json")
    plan = build_processing_plan(media, bundle, source_path="/media/Movies/Example Film (2024).mkv")

    command_plan = build_execution_command_plan(
        plan,
        input_path=media.file_path,
        scratch_dir="/scratch/encodr",
        ffmpeg_path="/usr/bin/ffmpeg",
        job_id="job-crf",
    )

    crf_index = command_plan.command.index("-crf")
    assert command_plan.command[crf_index + 1] == "22"


def test_ffmpeg_failure_marks_job_failed(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Example Film (2024).mkv")
        media.file_path.write_text("source", encoding="utf-8")
        job, plan = create_job(session, bundle, media, source_path=media.file_path.as_posix())

        service = WorkerExecutionService(runner=FailingRunner())
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed = session.get(Job, job.id)
        assert result.status == "failed"
        assert refreshed.status == JobStatus.FAILED
        assert refreshed.failure_message == "ffmpeg returned a non-zero exit status."


def test_verified_output_is_placed_and_marks_job_completed(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Remux Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        output_media = media_for_selected_streams(media, plan)

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=OutputVerifier(probe_client=StaticProbeClient(output_media)),
            replacement_service=ReplacementService(),
        )
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        refreshed_file = refreshed_job.tracked_file
        assert result.status == "completed"
        assert refreshed_job.status == JobStatus.COMPLETED
        assert refreshed_job.verification_status == DbVerificationStatus.PASSED
        assert refreshed_job.replacement_status == DbReplacementStatus.SUCCEEDED
        assert refreshed_job.final_output_path == source_path.as_posix()
        assert refreshed_file.lifecycle_state == FileLifecycleState.COMPLETED
        assert refreshed_file.compliance_state == ComplianceState.COMPLIANT
        assert source_path.read_text(encoding="utf-8") == "staged output"
        backup_path = source_path.with_name(f"{source_path.stem}.encodr-backup{source_path.suffix}")
        assert backup_path.exists()
        assert backup_path.read_text(encoding="utf-8") == "original"


def test_verification_failure_marks_job_failed_and_leaves_original_untouched(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Remux Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "bad-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=StaticVerifier.failed("Output verification failed."),
            replacement_service=ReplacementService(),
        )
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        refreshed_file = refreshed_job.tracked_file
        assert result.status == "failed"
        assert refreshed_job.status == JobStatus.FAILED
        assert refreshed_job.verification_status == DbVerificationStatus.FAILED
        assert refreshed_job.replacement_status == DbReplacementStatus.NOT_REQUIRED
        assert refreshed_file.lifecycle_state == FileLifecycleState.FAILED
        assert refreshed_file.compliance_state == ComplianceState.NON_COMPLIANT
        assert source_path.read_text(encoding="utf-8") == "original"
        assert staged_path.exists()


def test_compression_safety_uses_video_reduction_only_and_blocks_excessive_loss(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "compressed-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        output_media = media.model_copy(deep=True)
        output_media.container.size_bytes = max((media.container.size_bytes or 0) // 3, 1)
        output_media.video_streams[0].codec_name = "hevc"
        output_media.video_streams[0].bit_rate = 1_000_000

        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        plan.video.max_allowed_video_reduction_percent = 10

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=PassingVerifierWithProbeClient(output_media),
            replacement_service=ReplacementService(),
        )
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        assert result.status == "manual_review"
        assert result.failure_category == "compression_safety_bitrate_floor"
        assert refreshed_job.status == JobStatus.MANUAL_REVIEW
        assert refreshed_job.compression_reduction_percent is not None
        assert refreshed_job.compression_reduction_percent > 10
        assert source_path.read_text(encoding="utf-8") == "original"


def test_high_video_reduction_with_safe_output_bitrate_is_accepted(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "safe-compressed-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        output_media = media.model_copy(deep=True)
        output_media.container.size_bytes = max((media.container.size_bytes or 0) // 3, 1)
        output_media.video_streams[0].codec_name = "hevc"
        output_media.video_streams[0].bit_rate = 2_500_000

        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        plan.video.max_allowed_video_reduction_percent = 10

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=PassingVerifierWithProbeClient(output_media),
            replacement_service=StaticReplacementService.succeeded(source_path),
        )
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        assert result.status == "completed"
        assert result.output_video_bitrate_bps == 2_500_000
        assert refreshed_job.status == JobStatus.COMPLETED
        assert refreshed_job.compression_reduction_percent is not None
        assert refreshed_job.compression_reduction_percent > 10


def test_output_bitrate_fallback_from_size_and_duration_allows_safe_high_reduction(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.WARNING, logger="encodr.worker.loop")
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "safe-derived-bitrate-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        output_media = media.model_copy(deep=True)
        duration = output_media.container.duration_seconds
        assert duration is not None
        derived_video_bitrate = 2_500_000
        output_media.video_streams[0].codec_name = "hevc"
        output_media.video_streams[0].bit_rate = None
        output_media.container.size_bytes = int(
            (derived_video_bitrate * duration / 8)
            + ((output_media.audio_streams[0].bit_rate or 0) * duration / 8)
        )

        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        plan.video.max_allowed_video_reduction_percent = 10

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=PassingVerifierWithProbeClient(output_media),
            replacement_service=StaticReplacementService.succeeded(source_path),
        )
        JobRepository(session).mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        assert result.status == "completed"
        assert result.output_video_bitrate_bps == derived_video_bitrate
        assert refreshed_job.status == JobStatus.COMPLETED
        fallback_record = next(
            record
            for record in caplog.records
            if getattr(record, "event", None) == "bitrate_fallback_used"
        )
        assert getattr(fallback_record, "output_video_bitrate_bps", None) == derived_video_bitrate
        assert getattr(fallback_record, "diagnostic_type", None) == "worker_runtime"


def test_missing_output_bitrate_duration_and_size_send_to_review_with_reason(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.WARNING, logger="encodr.worker.loop")
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "unmeasurable-bitrate-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        output_media = media.model_copy(deep=True)
        output_media.video_streams[0].codec_name = "hevc"
        output_media.video_streams[0].bit_rate = None
        output_media.audio_streams[0].bit_rate = None
        output_media.container.duration_seconds = None
        output_media.container.size_bytes = None

        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        plan.video.max_allowed_video_reduction_percent = 10

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=PassingVerifierWithProbeClient(output_media),
            replacement_service=ReplacementService(),
        )
        JobRepository(session).mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        assert result.status == "manual_review"
        assert result.failure_category == "compression_safety_unmeasurable"
        assert refreshed_job.status == JobStatus.MANUAL_REVIEW
        assert "output_video_bitrate_bps" in (result.failure_message or "")
        assert "duration" in (result.failure_message or "").lower()
        assert "video size" in (result.failure_message or "").lower()
        unavailable_record = next(
            record
            for record in caplog.records
            if getattr(record, "event", None) == "bitrate_measurement_unavailable"
        )
        assert getattr(unavailable_record, "diagnostic_type", None) == "worker_runtime"
        assert "duration" in str(getattr(unavailable_record, "reason", "")).lower()


def test_output_larger_than_input_guard_sends_result_to_review(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "larger-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        output_media = media.model_copy(deep=True)
        output_media.container.size_bytes = int((media.container.size_bytes or 1) * 1.10)
        output_media.video_streams[0].codec_name = "hevc"
        output_media.video_streams[0].bit_rate = media.video_streams[0].bit_rate

        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        plan.video.output_larger_than_input_review_percent = 5

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=PassingVerifierWithProbeClient(output_media),
            replacement_service=ReplacementService(),
        )
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        assert result.status == "manual_review"
        assert result.failure_category == "output_larger_than_input"
        assert refreshed_job.status == JobStatus.MANUAL_REVIEW
        assert source_path.read_text(encoding="utf-8") == "original"


def test_output_larger_guard_uses_source_file_size_when_probe_metrics_are_missing(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="encodr.worker.loop")
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Animated Episode.mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_bytes(b"i" * 1000)
        staged_path = tmp_path / "scratch" / "animated-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("tv_episode.json"), source_path)
        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        plan.video.output_larger_than_input_review_percent = 5

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path, contents=b"o" * 1860),
            verifier=StaticVerifier.passed(),
            replacement_service=ReplacementService(),
        )
        JobRepository(session).mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        assert result.status == "manual_review"
        assert result.failure_category == "output_larger_than_input"
        assert "Output grew by 86.0%" in (result.failure_message or "")
        assert result.input_size_bytes == 1000
        assert result.output_size_bytes == 1860
        assert refreshed_job.status == JobStatus.MANUAL_REVIEW
        assert staged_path.exists()
        warning_record = next(
            record
            for record in caplog.records
            if getattr(record, "event", None) == "output_growth_guard_triggered"
        )
        assert warning_record.levelno == logging.WARNING
        assert getattr(warning_record, "diagnostic_type", None) == "worker_runtime"
        assert getattr(warning_record, "output_growth_guard_percent", None) == 5


def test_replacement_permission_denied_logs_error_with_errno_and_reason(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.ERROR, logger="encodr.worker.loop")
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Remux Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        output_media = media_for_selected_streams(media, plan)
        replacement = ReplacementResult(
            status=ReplacementStatus.FAILED,
            final_output_path=source_path,
            original_backup_path=source_path.with_name("Example Remux Film (2024).encodr-backup.mkv"),
            failure_message="Failed to move the source file to its backup path.",
            details={
                "operation": "move_source_to_backup",
                "errno": errno.EACCES,
                "reason": "permission denied",
                "permission_hint": "Check NAS share ownership, group membership, and write permissions.",
            },
        )
        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=OutputVerifier(probe_client=StaticProbeClient(output_media)),
            replacement_service=StaticReplacementService(replacement),
        )
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        assert result.status == "failed"
        error_record = next(
            record
            for record in caplog.records
            if getattr(record, "event", None) == "replacement_failed"
        )
        assert error_record.levelno == logging.ERROR
        assert getattr(error_record, "diagnostic_type", None) == "worker_runtime"
        assert getattr(error_record, "replacement_errno", None) == errno.EACCES
        assert getattr(error_record, "replacement_reason", None) == "permission denied"


def test_non_video_savings_do_not_trip_compression_safety(tmp_path: Path) -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        staged_path = tmp_path / "scratch" / "safe-output.mkv"
        staged_path.parent.mkdir(parents=True)

        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        output_media = media.model_copy(deep=True)
        output_media.container.size_bytes = max((media.container.size_bytes or 0) // 2, 1)
        output_media.video_streams[0].codec_name = "hevc"
        output_media.audio_streams = []
        output_media.subtitle_streams = []

        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        plan.video.max_allowed_video_reduction_percent = 10

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=PassingVerifierWithProbeClient(output_media),
            replacement_service=StaticReplacementService.succeeded(source_path),
        )
        jobs = JobRepository(session)
        jobs.mark_running(job, worker_name="worker-local")
        result = service.execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        refreshed_job = session.get(Job, job.id)
        assert result.status == "completed"
        assert refreshed_job.status == JobStatus.COMPLETED
        assert refreshed_job.compression_reduction_percent == 0


def test_packet_size_fallback_measures_video_reduction_without_stream_bitrates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mkv"
    output_path = tmp_path / "output.mkv"
    source_path.write_text("source", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    source_media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    output_media = media_at_path(parse_fixture("film_1080p.json"), output_path)
    source_media.container.size_bytes = 1_200_000
    output_media.container.size_bytes = 700_000

    for stream in [
        *source_media.video_streams,
        *source_media.audio_streams,
        *output_media.video_streams,
        *output_media.audio_streams,
    ]:
        stream.bit_rate = None

    packet_sizes = {
        source_path: {
            source_media.video_streams[0].index: 1_000_000,
            source_media.audio_streams[0].index: 200_000,
        },
        output_path: {
            output_media.video_streams[0].index: 550_000,
            output_media.audio_streams[0].index: 150_000,
        },
    }

    monkeypatch.setattr(
        "encodr_core.execution.metrics.probe_packet_sizes_by_stream",
        lambda file_path, *, ffprobe_path: packet_sizes[Path(file_path)],
    )

    metrics = calculate_media_savings(source_media, output_media, ffprobe_path="/usr/bin/ffprobe")

    assert metrics["video_input_size_bytes"] == 1_000_000
    assert metrics["video_output_size_bytes"] == 550_000
    assert metrics["video_space_saved_bytes"] == 450_000
    assert metrics["non_video_space_saved_bytes"] == 50_000
    assert metrics["compression_reduction_percent"] == 45.0


def test_empty_packet_probe_allows_container_minus_audio_video_size_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mkv"
    output_path = tmp_path / "output.mkv"
    source_path.write_text("source", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    source_media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    output_media = media_at_path(parse_fixture("film_1080p.json"), output_path)
    for media in (source_media, output_media):
        media.video_streams[0].bit_rate = None
        media.container.size_bytes = 10_000_000
        media.audio_streams[0].bit_rate = 800_000
        media.container.duration_seconds = 10

    monkeypatch.setattr(
        "encodr_core.execution.metrics.probe_packet_sizes_by_stream",
        lambda file_path, *, ffprobe_path: {},
    )

    metrics = calculate_media_savings(source_media, output_media, ffprobe_path="/usr/bin/ffprobe")

    assert metrics["video_input_size_bytes"] == 9_000_000
    assert metrics["video_output_size_bytes"] == 9_000_000
    assert metrics["output_video_bitrate_bps"] == 7_200_000
    assert metrics["output_video_bitrate_source"] == "derived_video_size_duration"


def test_worker_loop_processes_next_pending_job(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, future=True)

    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")

    with session_factory() as session:
        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    loop = LocalWorkerLoop(
        session_factory,
        bundle,
        execution_service=WorkerExecutionService(
            runner=StagedRunner(output_path=tmp_path / "scratch" / "loop.mkv"),
            verifier=PassingVerifierWithProbeClient(media_at_path(parse_fixture("film_1080p.json"), source_path)),
            replacement_service=StaticReplacementService.succeeded(source_path),
        ),
        poll_interval_seconds=0.01,
    )

    assert loop.run_once() is True
    with session_factory() as session:
        job = session.query(Job).one()
        assert job.status == JobStatus.COMPLETED
        assert job.verification_status == DbVerificationStatus.PASSED
        assert job.replacement_status == DbReplacementStatus.SUCCEEDED


def test_worker_loop_commits_running_state_before_execution(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    database_path = tmp_path / "worker-loop.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, future=True)

    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")

    with session_factory() as session:
        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    class AssertingExecutionService:
        def execute_job(self, session: Session, **kwargs):
            del session, kwargs
            with session_factory() as probe_session:
                job = probe_session.query(Job).one()
                assert job.status == JobStatus.RUNNING
            return ExecutionResult(
                mode="transcode",
                status="completed",
                command=["ffmpeg", "-i", "input.mkv", "output.mkv"],
                output_path=tmp_path / "scratch" / "loop.mkv",
                final_output_path=source_path,
                original_backup_path=source_path.with_name("Example Film (2024).encodr-backup.mkv"),
                output_size_bytes=1,
                exit_code=0,
                stdout="ok",
                stderr="",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

    loop = LocalWorkerLoop(
        session_factory,
        bundle,
        execution_service=AssertingExecutionService(),
        poll_interval_seconds=0.01,
    )

    assert loop.run_once() is True


def test_worker_execution_cancellation_removes_staged_output(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    staged_path = tmp_path / "scratch" / "cancelled.tmp.mkv"

    class CancelledRunner(ExecutionRunner):
        def execute_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            staged_path.write_text("partial output", encoding="utf-8")
            raise ExecutionCancelledError(
                "ffmpeg execution was cancelled by the operator.",
                file_path=tmp_path / "input.mkv",
                command=["ffmpeg", "-i", "input.mkv", staged_path.as_posix()],
                details={"output_path": staged_path.as_posix(), "exit_code": None},
            )

    with database_session() as session:
        source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original", encoding="utf-8")
        media = media_at_path(parse_fixture("film_1080p.json"), source_path)
        job, plan = create_job(session, bundle, media, source_path=source_path.as_posix())
        JobRepository(session).mark_running(job, worker_name="worker-local")

        result = WorkerExecutionService(runner=CancelledRunner()).execute_job(
            session,
            job_id=job.id,
            plan=plan,
            media_file=media,
            ffmpeg_path="/usr/bin/ffmpeg",
            scratch_dir=tmp_path / "scratch",
        )

        assert result.status == "cancelled"
        assert not staged_path.exists()
        assert job.status == JobStatus.CANCELLED
        assert job.tracked_file.last_processed_policy_version is None


def test_temp_output_path_handling() -> None:
    output_path = build_temp_output_path(
        Path("/media/Movies/Example Film (2024).mkv"),
        scratch_dir=Path("/scratch/encodr"),
        target_container=build_plan_target_container(),
        job_id="abc123",
    )

    assert output_path == Path("/scratch/encodr/Example Film (2024).abc123.tmp.mkv")


def create_job(
    session: Session,
    bundle,
    media: MediaFile,
    *,
    source_path: str,
) -> tuple[Job, ProcessingPlan]:
    tracked_files = TrackedFileRepository(session)
    probes = ProbeSnapshotRepository(session)
    plans = PlanSnapshotRepository(session)
    jobs = JobRepository(session)

    tracked_file = tracked_files.upsert_by_path(source_path, media_file=media)
    probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
    plan = build_processing_plan(media, bundle, source_path=source_path)
    plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
    tracked_files.update_file_state_from_plan_result(tracked_file, plan)
    job = jobs.create_job_from_plan(tracked_file, plan_snapshot)
    session.flush()
    return job, plan


def database_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def parse_fixture(name: str) -> MediaFile:
    return parse_ffprobe_json_output((FIXTURES_DIR / name).read_text(encoding="utf-8"), file_path=FIXTURES_DIR / name)


def media_at_path(media: MediaFile, file_path: Path) -> MediaFile:
    updated = media.model_copy(deep=True)
    updated.container.file_path = file_path
    updated.container.file_name = file_path.name
    updated.container.extension = file_path.suffix.lower().lstrip(".")
    return updated


def media_for_selected_streams(media: MediaFile, plan: ProcessingPlan) -> MediaFile:
    output_media = media.model_copy(deep=True)
    output_media.audio_streams = streams_in_plan_order(
        output_media.audio_streams,
        plan.selected_streams.audio_stream_indices,
    )
    primary_audio = (
        plan.audio.primary_stream_index
        if plan.audio.primary_stream_index is not None
        else (
            plan.selected_streams.audio_stream_indices[0]
            if plan.selected_streams.audio_stream_indices
            else None
        )
    )
    for stream in output_media.audio_streams:
        stream.disposition.default = stream.index == primary_audio

    output_media.subtitle_streams = streams_in_plan_order(
        output_media.subtitle_streams,
        plan.selected_streams.subtitle_stream_indices,
    )
    for stream in output_media.subtitle_streams:
        stream.disposition.default = stream.index == plan.subtitles.main_stream_index
    return output_media


def streams_in_plan_order(streams, selected_indices: list[int]):
    by_index = {stream.index: stream for stream in streams}
    return [by_index[index] for index in selected_indices if index in by_index]


def build_plan_target_container():
    bundle = load_config_bundle(project_root=REPO_ROOT)
    return bundle.policy.video.output_container


def _option_value(command: list[str], option: str) -> str | None:
    try:
        index = command.index(option)
    except ValueError:
        return None
    return command[index + 1]


class FailIfCalledClient:
    def run(self, command_plan):  # type: ignore[no-untyped-def]
        raise AssertionError("ffmpeg execution should not have been called")


class CapturingClient:
    def __init__(self) -> None:
        self.command_plan = None

    def run(self, command_plan):  # type: ignore[no-untyped-def]
        self.command_plan = command_plan
        return ExecutionResult(
            mode=command_plan.mode,
            status="staged",
            command=command_plan.command,
            output_path=command_plan.output_path,
            stdout="",
            stderr="",
            exit_code=0,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )


class StaticProbeClient:
    def __init__(self, media: MediaFile) -> None:
        self.media = media

    def probe_file(self, file_path):  # type: ignore[no-untyped-def]
        output_media = self.media.model_copy(deep=True)
        output_media.container.file_path = Path(file_path)
        output_media.container.file_name = Path(file_path).name
        output_media.container.extension = Path(file_path).suffix.lower().lstrip(".")
        return output_media


class StaticVerifier(OutputVerifier):
    def __init__(self, result: VerificationResult) -> None:
        self.result = result

    @classmethod
    def passed(cls) -> "StaticVerifier":
        return cls(VerificationResult(status=VerificationStatus.PASSED, passed=True))

    @classmethod
    def failed(cls, message: str) -> "StaticVerifier":
        return cls(
            VerificationResult(
                status=VerificationStatus.FAILED,
                passed=False,
                failures=[{"code": "verification_failed", "message": message, "metadata": {}}],
            )
        )

    def verify_output(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.result


class PassingVerifierWithProbeClient(StaticVerifier):
    def __init__(self, media: MediaFile) -> None:
        super().__init__(VerificationResult(status=VerificationStatus.PASSED, passed=True))
        self.probe_client = StaticProbeClient(media)


class StaticReplacementService(ReplacementService):
    def __init__(self, result: ReplacementResult) -> None:
        self.result = result

    @classmethod
    def succeeded(cls, final_output_path: Path) -> "StaticReplacementService":
        return cls(
            ReplacementResult(
                status=ReplacementStatus.SUCCEEDED,
                final_output_path=final_output_path,
            )
        )

    def place_verified_output(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.result


class StagedRunner(ExecutionRunner):
    def __init__(self, *, output_path: Path, contents: str | bytes = "staged output") -> None:
        self.output_path = output_path
        self.contents = contents

    def execute_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(self.contents, bytes):
            self.output_path.write_bytes(self.contents)
        else:
            self.output_path.write_text(self.contents, encoding="utf-8")
        return ExecutionResult(
            mode="remux",
            status="staged",
            command=["/usr/bin/ffmpeg", "-y"],
            output_path=self.output_path,
            stdout="ok",
            stderr="",
            exit_code=0,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )


class FailingRunner(ExecutionRunner):
    def execute_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise FFmpegProcessError(
            "ffmpeg returned a non-zero exit status.",
            file_path="/media/Movies/Example Film (2024).mkv",
            command=["/usr/bin/ffmpeg", "-y"],
            details={"exit_code": 1, "stderr": "bad input", "stdout": ""},
        )


def test_execute_plan_creates_missing_scratch_directory(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Example Film (2024).mkv")
    scratch_dir = tmp_path / "nested" / "scratch" / "encodr"
    client = CapturingClient()
    runner = ExecutionRunner(ffmpeg_client=client)
    plan = build_processing_plan(media, bundle, source_path=media.file_path.as_posix())

    result = runner.execute_plan(
        plan,
        input_path=media.file_path,
        scratch_dir=scratch_dir,
        ffmpeg_path="/usr/bin/ffmpeg",
        job_id="job-dir-create",
    )

    assert result.status == "staged"
    assert client.command_plan is not None
    assert client.command_plan.output_path is not None
    assert client.command_plan.output_path.parent.exists()
