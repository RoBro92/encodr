from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from encodr_core.config import load_config_bundle
from encodr_core.execution import ExecutionResult
from encodr_core.planning import build_processing_plan
from encodr_db import Base
from encodr_db.models import (
    JobStatus,
    ReplacementStatus,
    UserRole,
    Worker,
    WorkerHealthStatus,
    WorkerRegistrationStatus,
    WorkerType,
)
from encodr_db.repositories import (
    JobRepository,
    PlanSnapshotRepository,
    ProbeSnapshotRepository,
    RefreshTokenRepository,
    TrackedFileRepository,
    UserRepository,
)
from tests.helpers.api import import_api_module
from tests.helpers.db import create_session_factory, create_sqlite_engine
from tests.helpers.jobs import media_at_path, parse_fixture


pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class StaticPasswordHasher:
    def hash_password(self, password: str) -> str:
        return f"hashed:{password}"

    def verify_password(self, password: str, password_hash: str) -> bool:
        return password_hash == self.hash_password(password)


def test_atomic_refresh_token_rotation_allows_one_consumer(tmp_path: Path) -> None:
    _, session_factory = file_session_factory(tmp_path, "refresh-race.sqlite")

    with import_api_module("app.services.auth") as auth_module:
        security = importlib.import_module("app.core.security")
        core_auth = importlib.import_module("app.core.auth")
        audit = importlib.import_module("app.services.audit")
        token_service = security.TokenService(
            core_auth.AuthRuntimeSettings(
                secret_key="test-refresh-secret-with-sufficient-length",
                algorithm="HS256",
                access_token_ttl=timedelta(minutes=5),
                refresh_token_ttl=timedelta(days=1),
            )
        )
        service = auth_module.AuthService(
            password_hasher=StaticPasswordHasher(),
            token_service=token_service,
            audit_service=audit.AuditService(),
        )
        refresh_token = "initial-refresh-token"
        with session_factory() as session:
            user = UserRepository(session).create_user(
                username="admin",
                password_hash="hashed:password",
                role=UserRole.ADMIN,
                is_active=True,
            )
            RefreshTokenRepository(session).create_token(
                user_id=user.id,
                token_hash=token_service.hash_refresh_token(refresh_token),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
            session.commit()

        barrier = Barrier(2)

        def attempt_refresh() -> str:
            with session_factory() as session:
                barrier.wait()
                try:
                    service.refresh(session, request=request_stub(), refresh_token=refresh_token)
                    session.commit()
                    return "refreshed"
                except core_auth.InvalidTokenError:
                    session.commit()
                    return "invalid"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt_refresh(), range(2)))

        assert sorted(results) == ["invalid", "refreshed"]
        with session_factory() as session:
            tokens = RefreshTokenRepository(session).list_tokens_for_user(
                UserRepository(session).get_by_username("admin").id
            )
            assert len(tokens) == 2
            assert sum(token.revoked_at is None for token in tokens) == 1
            original = next(token for token in tokens if token.token_hash == token_service.hash_refresh_token(refresh_token))
            assert original.revoked_at is not None
            assert original.revocation_reason == "rotated"


def test_bootstrap_admin_creation_serializes_first_user(tmp_path: Path) -> None:
    _, session_factory = file_session_factory(tmp_path, "bootstrap-race.sqlite")

    with import_api_module("app.services.auth") as auth_module:
        security = importlib.import_module("app.core.security")
        core_auth = importlib.import_module("app.core.auth")
        audit = importlib.import_module("app.services.audit")
        service = auth_module.AuthService(
            password_hasher=StaticPasswordHasher(),
            token_service=security.TokenService(
                core_auth.AuthRuntimeSettings(
                    secret_key="test-bootstrap-secret-with-sufficient-length",
                    algorithm="HS256",
                    access_token_ttl=timedelta(minutes=5),
                    refresh_token_ttl=timedelta(days=1),
                )
            ),
            audit_service=audit.AuditService(),
        )
        barrier = Barrier(2)

        def attempt_bootstrap(username: str) -> str:
            with session_factory() as session:
                barrier.wait()
                try:
                    service.bootstrap_admin(
                        session,
                        request=request_stub(),
                        username=username,
                        password="super-secure-password",
                    )
                    session.commit()
                    return "created"
                except core_auth.BootstrapDisabledError:
                    session.commit()
                    return "blocked"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt_bootstrap, ["admin-a", "admin-b"]))

    assert sorted(results) == ["blocked", "created"]
    with session_factory() as session:
        users = UserRepository(session).list_users()
        assert len(users) == 1
        assert users[0].is_bootstrap_admin is True


def test_tracked_file_upsert_by_path_is_idempotent_under_concurrency(tmp_path: Path) -> None:
    _, session_factory = file_session_factory(tmp_path, "tracked-file-race.sqlite")
    media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Movie.mkv")
    barrier = Barrier(2)

    def upsert_once() -> str:
        with session_factory() as session:
            barrier.wait()
            tracked_file = TrackedFileRepository(session).upsert_by_path(
                media.file_path,
                media_file=media,
            )
            session.commit()
            return tracked_file.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: upsert_once(), range(2)))

    assert ids[0] == ids[1]
    with session_factory() as session:
        assert len(TrackedFileRepository(session).list_files()) == 1


def test_worker_claim_capacity_is_serialized_for_different_jobs(tmp_path: Path) -> None:
    _, session_factory = file_session_factory(tmp_path, "worker-claim-race.sqlite")
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("film_1080p.json")

    with session_factory() as session:
        worker = Worker(
            worker_key="remote-capacity",
            display_name="Remote Capacity",
            worker_type=WorkerType.REMOTE,
            enabled=True,
            registration_status=WorkerRegistrationStatus.REGISTERED,
            preferred_backend="cpu_only",
            allow_cpu_fallback=True,
            max_concurrent_jobs=1,
            last_health_status=WorkerHealthStatus.HEALTHY,
        )
        session.add(worker)
        job_ids = [
            create_pending_job(session, bundle, media_at_path(media, tmp_path / f"Movie {index}.mkv"))
            for index in range(2)
        ]
        worker_id = worker.id
        session.commit()

    barrier = Barrier(2)

    def claim(job_id: str) -> str | None:
        with session_factory() as session:
            worker = session.get(Worker, worker_id)
            barrier.wait()
            job = JobRepository(session).claim_pending_for_worker(
                job_id,
                worker=worker,
                requested_backend="cpu_only",
                max_running_assignments=1,
            )
            session.commit()
            return job.id if job is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_ids = list(executor.map(claim, job_ids))

    assert sum(job_id is not None for job_id in claimed_ids) == 1
    with session_factory() as session:
        jobs = [JobRepository(session).get_by_id(job_id) for job_id in job_ids]
        assert sum(job.status == JobStatus.RUNNING for job in jobs) == 1
        assert sum(job.status == JobStatus.PENDING for job in jobs) == 1


def test_bulk_queue_singleton_reuses_same_active_operation_under_concurrency(tmp_path: Path) -> None:
    _, session_factory = file_session_factory(tmp_path, "bulk-queue-race.sqlite")
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.bulk_queue") as bulk_module:
        service = bulk_module.BulkQueueService(
            config_bundle=bundle,
            session_factory=session_factory,
            probe_client_factory=lambda: None,
        )
        payload = SimpleNamespace(
            source_path=(tmp_path / "Movie.mkv").as_posix(),
            folder_path=None,
            selected_paths=[],
            preferred_worker_id=None,
            pinned_worker_id=None,
            preferred_backend_override=None,
            schedule_windows=[],
            backup_policy="keep",
        )
        barrier = Barrier(2)

        def create_operation() -> tuple[str, bool]:
            with session_factory() as session:
                barrier.wait()
                operation, created = service.create_operation(session, payload=payload)
                session.commit()
                return operation.id, created

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: create_operation(), range(2)))

    operation_ids = {operation_id for operation_id, _created in results}
    created_flags = sorted(created for _operation_id, created in results)
    assert len(operation_ids) == 1
    assert created_flags == [False, True]


def test_active_job_unique_violation_becomes_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, session_factory = file_session_factory(tmp_path, "active-job-conflict.sqlite")
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Movie.mkv")

    with import_api_module("app.services.jobs") as jobs_module:
        with session_factory() as session:
            tracked_file, plan_snapshot = create_planned_target(session, bundle, media)
            JobRepository(session).create_job_from_plan(tracked_file, plan_snapshot)
            session.commit()

        calls = 0
        original = JobRepository.has_active_job_for_tracked_file

        def stale_precheck(self, tracked_file_id: str) -> bool:
            nonlocal calls
            calls += 1
            if calls == 1:
                return False
            return original(self, tracked_file_id)

        monkeypatch.setattr(JobRepository, "has_active_job_for_tracked_file", stale_precheck)

        with session_factory() as session:
            with pytest.raises(jobs_module.ApiConflictError):
                jobs_module.JobsService().create_job(
                    session,
                    tracked_file_id=tracked_file.id,
                    plan_snapshot_id=plan_snapshot.id,
                )


def test_restore_backup_is_blocked_while_replacement_job_is_active(tmp_path: Path) -> None:
    _, session_factory = file_session_factory(tmp_path, "restore-active-job.sqlite")
    bundle = load_config_bundle(project_root=REPO_ROOT)
    source_path = tmp_path / "Movie.mkv"
    replacement_path = tmp_path / "Movie.encodr.mkv"
    backup_path = tmp_path / "Movie.encodr-backup.mkv"
    source_path.write_text("source", encoding="utf-8")
    replacement_path.write_text("replacement", encoding="utf-8")
    backup_path.write_text("backup", encoding="utf-8")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)

    with import_api_module("app.services.jobs") as jobs_module:
        with session_factory() as session:
            tracked_file, plan_snapshot = create_planned_target(session, bundle, media)
            backup_job = JobRepository(session).create_job_from_plan(tracked_file, plan_snapshot)
            backup_job.status = JobStatus.COMPLETED
            backup_job.replacement_status = ReplacementStatus.SUCCEEDED
            backup_job.final_output_path = replacement_path.as_posix()
            backup_job.original_backup_path = backup_path.as_posix()
            session.flush()
            JobRepository(session).create_job_from_plan(tracked_file, plan_snapshot)
            backup_job_id = backup_job.id
            session.commit()

        with session_factory() as session:
            with pytest.raises(jobs_module.ApiConflictError):
                jobs_module.JobsService().restore_backup(session, job_id=backup_job_id)

    assert backup_path.exists()
    assert replacement_path.exists()
    assert source_path.read_text(encoding="utf-8") == "source"


def test_automatic_retry_skips_when_another_active_job_exists(tmp_path: Path) -> None:
    _, session_factory = file_session_factory(tmp_path, "automatic-retry-conflict.sqlite")
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Movie.mkv")
    failed_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        tracked_file, plan_snapshot = create_planned_target(session, bundle, media)
        jobs = JobRepository(session)
        failed_job = jobs.create_job_from_plan(tracked_file, plan_snapshot)
        result = ExecutionResult(
            mode="failed",
            status="failed",
            command=[],
            output_path=None,
            failure_message="ffmpeg failed.",
            failure_category="execution_failed",
            started_at=failed_at,
            completed_at=failed_at,
        )
        jobs.mark_result(failed_job, result)
        jobs.create_job_from_plan(tracked_file, plan_snapshot)

        assert jobs.apply_automatic_retry_policy(failed_job, result) is None
        assert sum(
            job.status in {JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING}
            for job in tracked_file.jobs
        ) == 1


def file_session_factory(tmp_path: Path, name: str):
    engine = create_sqlite_engine(
        f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}",
        use_static_pool=False,
    )
    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


def request_stub():
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


def create_pending_job(session, bundle, media) -> str:
    tracked_file, plan_snapshot = create_planned_target(session, bundle, media)
    return JobRepository(session).create_job_from_plan(tracked_file, plan_snapshot).id


def create_planned_target(session, bundle, media):
    tracked_files = TrackedFileRepository(session)
    probes = ProbeSnapshotRepository(session)
    plans = PlanSnapshotRepository(session)
    tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
    probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
    plan = build_processing_plan(media, bundle, source_path=media.file_path)
    plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
    tracked_files.update_file_state_from_plan_result(tracked_file, plan)
    return tracked_file, plan_snapshot
