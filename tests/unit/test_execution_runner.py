from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.executor.loop import LocalWorkerLoop
from app.executor.service import WorkerExecutionService
from encodr_core.config import load_config_bundle
from encodr_core.execution import (
    ExecutionResult,
    ExecutionRunner,
    FFmpegProcessError,
    build_execution_command_plan,
    build_temp_output_path,
)
from encodr_core.media.models import MediaFile
from encodr_core.planning import PlanAction, ProcessingPlan, build_processing_plan
from encodr_core.probe import parse_ffprobe_json_output
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus
from encodr_db import Base
from encodr_db.models import ComplianceState, FileLifecycleState, Job, JobStatus, ReplacementStatus as DbReplacementStatus, VerificationStatus as DbVerificationStatus
from encodr_db.repositories import JobRepository, PlanSnapshotRepository, ProbeSnapshotRepository, TrackedFileRepository

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
        assert refreshed.status == JobStatus.SKIPPED
        assert refreshed.verification_status == DbVerificationStatus.NOT_REQUIRED
        assert refreshed.replacement_status == DbReplacementStatus.NOT_REQUIRED


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
    assert command_plan.output_path == Path("/scratch/encodr/Example Remux Film (2024).job-123.tmp.mkv")


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

        service = WorkerExecutionService(
            runner=StagedRunner(output_path=staged_path),
            verifier=OutputVerifier(probe_client=StaticProbeClient(media)),
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
            verifier=StaticVerifier.passed(),
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


def build_plan_target_container():
    bundle = load_config_bundle(project_root=REPO_ROOT)
    return bundle.policy.video.output_container


class FailIfCalledClient:
    def run(self, command_plan):  # type: ignore[no-untyped-def]
        raise AssertionError("ffmpeg execution should not have been called")


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
    def __init__(self, *, output_path: Path) -> None:
        self.output_path = output_path

    def execute_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("staged output", encoding="utf-8")
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
