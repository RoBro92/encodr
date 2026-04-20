from __future__ import annotations

from datetime import datetime, timezone

import pytest

from encodr_db.models import WorkerHealthStatus
from encodr_db.repositories import WorkerRepository
from tests.helpers.db import create_schema_session_factory


pytestmark = [pytest.mark.unit]


def test_worker_registration_and_lookup_updates_existing_record() -> None:
    _, session_factory = create_schema_session_factory()

    with session_factory() as session:
        repository = WorkerRepository(session)
        first = repository.register_remote_worker(
            worker_key="worker-remote-1",
            display_name="Remote Worker 1",
            auth_token_hash="hash-1",
            host_metadata={"hostname": "remote-a"},
            capability_payload={"execution_modes": ["remux"]},
            runtime_payload={"queue": "remote"},
            binary_payload={"binaries": []},
            health_status=WorkerHealthStatus.HEALTHY,
            health_summary="Ready",
            registered_at=datetime.now(timezone.utc),
        )
        second = repository.register_remote_worker(
            worker_key="worker-remote-1",
            display_name="Remote Worker 1B",
            auth_token_hash="hash-2",
            host_metadata={"hostname": "remote-b"},
            capability_payload={"execution_modes": ["remux", "transcode"]},
            runtime_payload={"queue": "remote"},
            binary_payload={"binaries": [{"name": "ffmpeg"}]},
            health_status=WorkerHealthStatus.DEGRADED,
            health_summary="Warning",
            registered_at=datetime.now(timezone.utc),
        )

        assert first.id == second.id
        assert second.display_name == "Remote Worker 1B"
        assert repository.get_by_key("worker-remote-1").auth_token_hash == "hash-2"


def test_worker_heartbeat_updates_last_seen_and_capabilities() -> None:
    _, session_factory = create_schema_session_factory()

    with session_factory() as session:
        repository = WorkerRepository(session)
        worker = repository.register_remote_worker(
            worker_key="worker-remote-2",
            display_name="Remote Worker 2",
            auth_token_hash="hash-2",
            host_metadata={"hostname": "remote"},
            capability_payload={"execution_modes": ["remux"]},
            runtime_payload=None,
            binary_payload=None,
            health_status=WorkerHealthStatus.UNKNOWN,
            health_summary=None,
            registered_at=datetime.now(timezone.utc),
        )
        heartbeat_at = datetime.now(timezone.utc)
        repository.record_heartbeat(
            worker,
            heartbeat_at=heartbeat_at,
            health_status=WorkerHealthStatus.HEALTHY,
            health_summary="Heartbeat healthy",
            capability_payload={"execution_modes": ["remux", "transcode"]},
            runtime_payload={"queue": "remote"},
            binary_payload={"binaries": [{"name": "ffprobe"}]},
            host_metadata={"hostname": "remote-updated"},
        )

        assert worker.last_seen_at == heartbeat_at
        assert worker.last_health_status == WorkerHealthStatus.HEALTHY
        assert worker.capability_payload["execution_modes"] == ["remux", "transcode"]
        assert worker.runtime_payload["queue"] == "remote"


def test_worker_enable_disable_updates_registration_state() -> None:
    _, session_factory = create_schema_session_factory()

    with session_factory() as session:
        repository = WorkerRepository(session)
        worker = repository.register_remote_worker(
            worker_key="worker-remote-3",
            display_name="Remote Worker 3",
            auth_token_hash="hash-3",
            host_metadata=None,
            capability_payload=None,
            runtime_payload=None,
            binary_payload=None,
            health_status=WorkerHealthStatus.HEALTHY,
            health_summary="Ready",
            registered_at=datetime.now(timezone.utc),
        )

        repository.set_enabled(worker, enabled=False)
        assert worker.enabled is False
        assert worker.last_health_status == WorkerHealthStatus.UNKNOWN

        repository.set_enabled(worker, enabled=True)
        assert worker.enabled is True
