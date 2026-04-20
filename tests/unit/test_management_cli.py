from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

import encodr_cli
from encodr_db.models import AuditEventType, UserRole
from encodr_db.repositories import AuditEventRepository, UserRepository
from tests.helpers.api import load_api_security_module
from tests.helpers.db import create_migrated_session_factory


def test_command_version_prints_release_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle())

    result = encodr_cli.command_version(argparse.Namespace(project_root="."))

    output = capsys.readouterr().out
    assert result == 0
    assert "Encodr 0.1.0" in output
    assert "API base path: /api" in output


def test_command_doctor_reports_runtime_and_storage_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle())
    monkeypatch.setattr(encodr_cli, "create_session_factory", lambda _bundle: object())
    monkeypatch.setattr(encodr_cli, "check_api_health", lambda _bundle: {"status": "healthy", "summary": "API responded with ok."})

    class FakeSystemService:
        def __init__(self, **_kwargs) -> None:
            pass

        def runtime_status(self) -> dict[str, object]:
            return {
                "version": "0.1.0",
                "status": "healthy",
                "summary": "Runtime health is healthy.",
                "db_reachable": True,
                "schema_reachable": True,
                "first_user_setup_required": False,
            }

        def storage_status(self) -> dict[str, object]:
            healthy_path = {
                "role": "scratch",
                "status": "healthy",
                "path": "/srv/encodr/scratch",
            }
            return {
                "status": "healthy",
                "summary": "Configured storage paths are healthy.",
                "scratch": healthy_path,
                "data_dir": {**healthy_path, "role": "data", "path": "/srv/encodr/data"},
                "media_mounts": [{**healthy_path, "role": "media_mount", "path": "/mnt/media"}],
            }

    monkeypatch.setattr(encodr_cli, "get_system_service_class", lambda: FakeSystemService)

    result = encodr_cli.command_doctor(argparse.Namespace(project_root="."))

    output = capsys.readouterr().out
    assert result == 0
    assert "Version: 0.1.0" in output
    assert "API health: healthy" in output


def test_command_reset_admin_creates_first_admin(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'cli-reset-admin.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(repo_root=repo_root, database_url=database_url)
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle(database_url=database_url))
    monkeypatch.setattr(
        encodr_cli,
        "get_password_hash_service_class",
        lambda: load_api_security_module().PasswordHashService,
    )

    result = encodr_cli.command_reset_admin(
        argparse.Namespace(project_root=".", username="admin", password="super-secure-password"),
    )

    assert result == 0
    with session_factory() as session:
        user = UserRepository(session).get_by_username("admin")
        assert user is not None
        assert user.role == UserRole.ADMIN
        assert user.password_hash != "super-secure-password"
        events = AuditEventRepository(session).list_events(limit=20)
        assert any(event.event_type == AuditEventType.ADMIN_RESET for event in events)


def test_command_mount_setup_validation_mode_checks_target_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mount_path = tmp_path / "media"
    mount_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle(media_mount=str(mount_path)))

    result = encodr_cli.command_mount_setup(
        argparse.Namespace(
            project_root=".",
            type="nfs",
            host_source=None,
            host_mount="/mnt/pve/encodr-media",
            container_target=str(mount_path),
            create_dirs=False,
            validate_only=True,
        ),
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "Recommended model: mount the share on the Proxmox host" in output
    assert "Readable from LXC: yes" in output


def test_install_script_includes_bootstrap_and_health_steps(repo_root: Path) -> None:
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")

    assert "./infra/scripts/bootstrap.sh" in install_script
    assert "docker compose up -d --build" in install_script
    assert "./encodr doctor" in install_script


def fake_bundle(*, database_url: str = "sqlite+pysqlite:///:memory:", media_mount: str = "/mnt/media"):
    return SimpleNamespace(
        app=SimpleNamespace(
            environment=SimpleNamespace(value="development"),
            api=SimpleNamespace(base_path="/api", port=8000),
            ui=SimpleNamespace(public_url="http://localhost:5173"),
            database=SimpleNamespace(dsn=database_url),
            auth=SimpleNamespace(password_hash_scheme="argon2id"),
            update=SimpleNamespace(
                enabled=False,
                metadata_url=None,
                channel="internal",
                check_timeout_seconds=5,
            ),
        ),
        workers=SimpleNamespace(
            local=SimpleNamespace(
                media_mounts=[Path(media_mount)],
            ),
        ),
    )
