from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from encodr_core.config import ConfigBundle, load_config_bundle
from encodr_core.execution import ExecutionResult, ExecutionRunner, FFmpegProcessError
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan, build_processing_plan
from encodr_core.probe import parse_ffprobe_json_output
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus
from encodr_db.models import Job
from encodr_db.repositories import JobRepository, PlanSnapshotRepository, ProbeSnapshotRepository, TrackedFileRepository

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ffprobe"


@dataclass(frozen=True, slots=True)
class PersistedJobContext:
    job: Job
    plan: ProcessingPlan
    media_file: MediaFile


def parse_fixture(name: str) -> MediaFile:
    return parse_ffprobe_json_output(
        (FIXTURES_DIR / name).read_text(encoding="utf-8"),
        file_path=FIXTURES_DIR / name,
    )


def media_at_path(media: MediaFile, file_path: Path) -> MediaFile:
    updated = media.model_copy(deep=True)
    updated.container.file_path = file_path
    updated.container.file_name = file_path.name
    updated.container.extension = file_path.suffix.lower().lstrip(".")
    return updated


def create_job(
    session: Session,
    bundle: ConfigBundle,
    media_file: MediaFile,
    *,
    source_path: str,
) -> PersistedJobContext:
    tracked_files = TrackedFileRepository(session)
    probes = ProbeSnapshotRepository(session)
    plans = PlanSnapshotRepository(session)
    jobs = JobRepository(session)

    tracked_file = tracked_files.upsert_by_path(source_path, media_file=media_file)
    probe_snapshot = probes.add_probe_snapshot(tracked_file, media_file)
    plan = build_processing_plan(media_file, bundle, source_path=source_path)
    plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
    tracked_files.update_file_state_from_plan_result(tracked_file, plan)
    job = jobs.create_job_from_plan(tracked_file, plan_snapshot)
    session.flush()
    return PersistedJobContext(job=job, plan=plan, media_file=media_file)


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
    def __init__(self, *, output_path: Path, mode: str = "remux") -> None:
        self.output_path = output_path
        self.mode = mode

    def execute_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("staged output", encoding="utf-8")
        return ExecutionResult(
            mode=self.mode,
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
