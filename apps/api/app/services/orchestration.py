from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.services.errors import ApiNotFoundError, ApiValidationError
from app.services.files import FilesService
from app.services.jobs import JobsService
from app.services.library import LibraryService
from app.services.plans import PlansService
from encodr_core.config import ConfigBundle
from encodr_db.models import JobStatus, WorkerType
from encodr_db.repositories import JobRepository, ScanRecordRepository, TrackedFileRepository, WatchedJobRepository, WorkerRepository
from encodr_db.runtime import worker_is_dispatchable
from encodr_shared.scheduling import next_schedule_opening, normalise_schedule_windows, schedule_windows_allow_now, schedule_windows_summary

logger = logging.getLogger("encodr.orchestration")

RULESET_NAMES = {"movies", "movies_4k", "tv", "tv_4k"}
MEDIA_CLASSES = {"movie", "movie_4k", "tv", "tv_4k", "mixed"}


@dataclass(slots=True)
class OrchestrationSummary:
    scanned_watchers: int = 0
    queued_jobs: int = 0
    staged_files: int = 0
    promoted_jobs: int = 0
    interrupted_jobs: int = 0
    expired_backups: int = 0


class OrchestrationService:
    def __init__(
        self,
        *,
        config_bundle: ConfigBundle,
        session_factory: sessionmaker[Session],
        probe_client_factory,
    ) -> None:
        self.config_bundle = config_bundle
        self.session_factory = session_factory
        self.probe_client_factory = probe_client_factory

    def list_recent_scans(self, session: Session, *, limit: int = 20) -> list[dict[str, object]]:
        repository = ScanRecordRepository(session)
        return [self._scan_record_payload(item) for item in repository.list_recent(limit=limit)]

    def get_scan(self, session: Session, *, scan_id: str) -> dict[str, object]:
        record = ScanRecordRepository(session).get_by_id(scan_id)
        if record is None:
            raise ApiNotFoundError("Scan record could not be found.")
        return self._scan_record_payload(record)

    def persist_scan(
        self,
        session: Session,
        *,
        source_path: str,
        allow_external: bool = False,
        source_kind: str = "manual",
        watched_job_id: str | None = None,
    ) -> dict[str, object]:
        library = LibraryService(config_bundle=self.config_bundle)
        summary = library.scan_directory(
            source_path,
            allow_external=allow_external,
            source_kind=source_kind,
        )
        record = ScanRecordRepository(session).add_scan_record(
            source_path=summary["folder_path"],
            root_path=summary["root_path"],
            source_kind=source_kind,
            watched_job_id=watched_job_id,
            directory_count=int(summary["directory_count"]),
            direct_directory_count=int(summary["direct_directory_count"]),
            video_file_count=int(summary["video_file_count"]),
            likely_show_count=int(summary["likely_show_count"]),
            likely_season_count=int(summary["likely_season_count"]),
            likely_episode_count=int(summary["likely_episode_count"]),
            likely_film_count=int(summary["likely_film_count"]),
            files_payload=list(summary["files"]),
        )
        tracked_files = TrackedFileRepository(session)
        for file_payload in summary["files"]:
            source = Path(str(file_payload["path"]))
            try:
                stat_result = source.stat()
                observed_modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
                observed_size = stat_result.st_size
            except OSError:
                observed_modified_at = None
                observed_size = int(file_payload["size_bytes"]) if file_payload.get("size_bytes") is not None else None
            tracked_files.upsert_by_path(
                source,
                last_observed_size=observed_size,
                last_observed_modified_time=observed_modified_at,
            )
        return self._scan_record_payload(record)

    def list_watched_jobs(self, session: Session) -> list[dict[str, object]]:
        repository = WatchedJobRepository(session)
        return [self._watched_job_payload(item) for item in repository.list_watched_jobs()]

    def create_or_update_watched_job(
        self,
        session: Session,
        *,
        watched_job_id: str | None,
        display_name: str,
        source_path: str,
        media_class: str,
        ruleset_override: str | None,
        preferred_worker_id: str | None,
        pinned_worker_id: str | None,
        preferred_backend: str | None,
        schedule_windows: list[dict] | None,
        auto_queue: bool,
        stage_only: bool,
        enabled: bool,
    ) -> dict[str, object]:
        resolved = Path(source_path).expanduser()
        if not resolved.exists():
            raise ApiValidationError("Watched source path does not exist.")
        if not resolved.is_dir():
            raise ApiValidationError("Watched source path must be a directory.")
        if media_class not in MEDIA_CLASSES:
            raise ApiValidationError("Unsupported watched media class.")
        if ruleset_override is not None and ruleset_override not in RULESET_NAMES:
            raise ApiValidationError("Unsupported ruleset override.")
        try:
            cleaned_schedule = normalise_schedule_windows(schedule_windows)
        except ValueError as error:
            raise ApiValidationError(str(error)) from error
        if preferred_worker_id and pinned_worker_id and preferred_worker_id == pinned_worker_id:
            preferred_worker_id = pinned_worker_id

        workers = WorkerRepository(session)
        if preferred_worker_id and workers.get_by_id(preferred_worker_id) is None:
            raise ApiValidationError("Preferred worker could not be found.")
        if pinned_worker_id and workers.get_by_id(pinned_worker_id) is None:
            raise ApiValidationError("Pinned worker could not be found.")

        watched = WatchedJobRepository(session).create_or_update(
            watched_job_id=watched_job_id,
            display_name=display_name.strip() or resolved.name,
            source_path=resolved.resolve().as_posix(),
            media_class=media_class,
            ruleset_override=ruleset_override,
            preferred_worker_id=preferred_worker_id,
            pinned_worker_id=pinned_worker_id,
            preferred_backend=preferred_backend,
            schedule_windows=cleaned_schedule,
            auto_queue=auto_queue,
            stage_only=stage_only,
            enabled=enabled,
        )
        return self._watched_job_payload(watched)

    def run_once(self) -> OrchestrationSummary:
        summary = OrchestrationSummary()
        with self.session_factory() as session:
            summary.expired_backups += len(JobsService().cleanup_expired_backups(session))
            summary.promoted_jobs += self._refresh_scheduled_jobs(session)
            watcher_summary = self._refresh_watched_jobs(session)
            summary.scanned_watchers += watcher_summary.scanned_watchers
            summary.queued_jobs += watcher_summary.queued_jobs
            summary.staged_files += watcher_summary.staged_files
            summary.interrupted_jobs += self._handle_worker_interruptions(session)
            session.commit()
        return summary

    def _refresh_scheduled_jobs(self, session: Session) -> int:
        repository = JobRepository(session)
        changed = 0
        now = datetime.now(timezone.utc)
        for job in repository.list_jobs_for_scheduling():
            scheduled_for_at = _normalise_datetime(job.scheduled_for_at) if job.scheduled_for_at is not None else None
            if job.status == JobStatus.SCHEDULED and scheduled_for_at is not None and scheduled_for_at > now:
                continue
            if schedule_windows_allow_now(job.schedule_windows, now=now):
                if job.status == JobStatus.SCHEDULED:
                    repository.promote_scheduled(job)
                    changed += 1
                continue
            if not job.schedule_windows:
                continue
            if job.status == JobStatus.PENDING and job.assigned_worker_id is None:
                repository.mark_scheduled(job, scheduled_for_at=next_schedule_opening(job.schedule_windows, now=now))
                changed += 1
            elif job.status == JobStatus.SCHEDULED:
                repository.mark_scheduled(job, scheduled_for_at=next_schedule_opening(job.schedule_windows, now=now))
                changed += 1
        return changed

    def _refresh_watched_jobs(self, session: Session) -> OrchestrationSummary:
        summary = OrchestrationSummary()
        watch_repository = WatchedJobRepository(session)
        jobs_service = JobsService()
        plans_service = PlansService(
            config_bundle=self.config_bundle,
            files_service=FilesService(
                config_bundle=self.config_bundle,
                probe_client_factory=self.probe_client_factory,
            ),
        )
        for watched in watch_repository.list_watched_jobs(enabled=True):
            summary.scanned_watchers += 1
            scan_payload = self.persist_scan(
                session,
                source_path=watched.source_path,
                allow_external=True,
                source_kind="watched",
                watched_job_id=watched.id,
            )
            current_paths = [str(item["path"]) for item in scan_payload["files"]]
            previous_paths = set(watched.last_seen_paths or [])
            new_paths = [path for path in current_paths if path not in previous_paths]
            queued_any = False
            for source_path in new_paths:
                tracked_file, _probe_snapshot, plan_snapshot = plans_service.plan_file(
                    session,
                    source_path=source_path,
                    ruleset_override=watched.ruleset_override,
                )
                if watched.auto_queue and not watched.stage_only:
                    job = jobs_service.create_watched_job_if_needed(
                        session,
                        tracked_file=tracked_file,
                        plan_snapshot=plan_snapshot,
                        watched_job_id=watched.id,
                        preferred_worker_id=watched.preferred_worker_id,
                        pinned_worker_id=watched.pinned_worker_id,
                        preferred_backend_override=watched.preferred_backend,
                        schedule_windows=watched.schedule_windows,
                    )
                    if job is not None:
                        summary.queued_jobs += 1
                        queued_any = True
                else:
                    summary.staged_files += 1
            watch_repository.update_last_scan(
                watched,
                last_scan_record_id=str(scan_payload["scan_id"]),
                last_seen_paths=current_paths,
                scanned_at=_parse_datetime(scan_payload["scanned_at"]),
                enqueue_at=datetime.now(timezone.utc) if queued_any else None,
            )
        return summary

    def _handle_worker_interruptions(self, session: Session) -> int:
        repository = JobRepository(session)
        interrupted = 0
        now = datetime.now(timezone.utc)
        grace_period = timedelta(seconds=45)
        for job in repository.list_running_jobs():
            worker = job.assigned_worker
            last_contact = job.progress_updated_at or job.started_at or job.updated_at
            if last_contact.tzinfo is None:
                last_contact = last_contact.replace(tzinfo=timezone.utc)
            if last_contact >= now - grace_period:
                continue
            if worker is None:
                repository.mark_interrupted(
                    job,
                    interrupted_at=now,
                    reason="Worker assignment was lost before the job completed.",
                )
                interrupted += 1
                continue
            if worker.worker_type == WorkerType.REMOTE and worker_is_dispatchable(worker, now=now):
                continue
            if worker.worker_type == WorkerType.LOCAL and worker.enabled:
                continue
            repository.mark_interrupted(
                job,
                interrupted_at=now,
                reason=(
                    "The assigned worker went offline or stopped responding. "
                    "Retry the job to restart it from the beginning."
                ),
            )
            interrupted += 1
        return interrupted

    @staticmethod
    def _scan_record_payload(record) -> dict[str, object]:
        return {
            "scan_id": record.id,
            "folder_path": record.source_path,
            "root_path": record.root_path,
            "source_kind": record.source_kind,
            "watched_job_id": record.watched_job_id,
            "scanned_at": record.scanned_at,
            "stale": record.stale,
            "directory_count": record.directory_count,
            "direct_directory_count": record.direct_directory_count,
            "video_file_count": record.video_file_count,
            "likely_show_count": record.likely_show_count,
            "likely_season_count": record.likely_season_count,
            "likely_episode_count": record.likely_episode_count,
            "likely_film_count": record.likely_film_count,
            "files": list(record.files_payload or []),
        }

    @staticmethod
    def _watched_job_payload(watched) -> dict[str, object]:
        return {
            "id": watched.id,
            "display_name": watched.display_name,
            "source_path": watched.source_path,
            "media_class": watched.media_class,
            "ruleset_override": watched.ruleset_override,
            "preferred_worker_id": watched.preferred_worker_id,
            "pinned_worker_id": watched.pinned_worker_id,
            "preferred_backend": watched.preferred_backend,
            "schedule_windows": watched.schedule_windows or [],
            "schedule_summary": schedule_windows_summary(watched.schedule_windows),
            "auto_queue": watched.auto_queue,
            "stage_only": watched.stage_only,
            "enabled": watched.enabled,
            "last_scan_record_id": watched.last_scan_record_id,
            "last_scan_at": watched.last_scan_at,
            "last_enqueue_at": watched.last_enqueue_at,
            "last_seen_count": len(watched.last_seen_paths or []),
            "created_at": watched.created_at,
            "updated_at": watched.updated_at,
        }


class BackgroundOrchestrationLoop:
    def __init__(
        self,
        *,
        orchestration_service: OrchestrationService,
        poll_interval_seconds: float = 15.0,
    ) -> None:
        self.orchestration_service = orchestration_service
        self.poll_interval_seconds = poll_interval_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self.run_forever, name="encodr-orchestration", daemon=True)
        self._thread.start()

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.orchestration_service.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("orchestration loop failed")
            self._stop_event.wait(self.poll_interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError("Unsupported datetime value.")


def _normalise_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
