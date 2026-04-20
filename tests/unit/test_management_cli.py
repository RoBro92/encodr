from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import encodr_cli
from encodr_db.models import AuditEventType, UserRole
from encodr_db.repositories import AuditEventRepository, UserRepository
from encodr_shared.versioning import read_version
from tests.helpers.api import load_api_security_module
from tests.helpers.db import create_migrated_session_factory

CURRENT_VERSION = read_version(Path(__file__))


def test_command_version_prints_release_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle())

    result = encodr_cli.command_version(argparse.Namespace(project_root="."))

    output = capsys.readouterr().out
    assert result == 0
    assert f"Encodr {CURRENT_VERSION}" in output
    assert "API base path: /api" in output


def test_command_doctor_reports_runtime_and_storage_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(encodr_cli, "should_use_dockerised_doctor", lambda _root: False)
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle())
    monkeypatch.setattr(encodr_cli, "create_session_factory", lambda _bundle: object())
    monkeypatch.setattr(encodr_cli, "check_api_health", lambda _bundle: {"status": "healthy", "summary": "API responded with ok."})

    class FakeSystemService:
        def __init__(self, **_kwargs) -> None:
            pass

        def runtime_status(self) -> dict[str, object]:
            return {
                "version": CURRENT_VERSION,
                "status": "healthy",
                "summary": "Runtime health is healthy.",
                "db_reachable": True,
                "schema_reachable": True,
                "first_user_setup_required": False,
            }

        def storage_status(self) -> dict[str, object]:
            healthy_path = {
                "role": "scratch",
                "display_name": "Scratch workspace",
                "status": "healthy",
                "path": "/srv/encodr/scratch",
                "message": "The path is available.",
                "recommended_action": None,
            }
            return {
                "status": "healthy",
                "summary": "Configured storage paths are healthy.",
                "scratch": healthy_path,
                "data_dir": {**healthy_path, "role": "data", "display_name": "Application data", "path": "/srv/encodr/data"},
                "media_mounts": [{**healthy_path, "role": "media_mount", "display_name": "Media library", "path": "/media"}],
            }

    monkeypatch.setattr(encodr_cli, "get_system_service_class", lambda: FakeSystemService)

    result = encodr_cli.command_doctor(argparse.Namespace(project_root="."))

    output = capsys.readouterr().out
    assert result == 0
    assert f"Version: {CURRENT_VERSION}" in output
    assert "Doctor mode: host-direct" in output
    assert "API health: healthy" in output


def test_command_status_reports_media_mount_problem_clearly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(encodr_cli, "should_use_dockerised_doctor", lambda _root: False)
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle())
    monkeypatch.setattr(encodr_cli, "create_session_factory", lambda _bundle: object())
    monkeypatch.setattr(encodr_cli, "check_api_health", lambda _bundle: {"status": "healthy", "summary": "API responded with ok."})

    class FakeSystemService:
        def __init__(self, **_kwargs) -> None:
            pass

        def runtime_status(self) -> dict[str, object]:
            return {
                "version": CURRENT_VERSION,
                "status": "degraded",
                "summary": "Runtime health completed with warnings.",
                "db_reachable": True,
                "schema_reachable": True,
                "first_user_setup_required": False,
            }

        def storage_status(self) -> dict[str, object]:
            healthy_path = {
                "role": "scratch",
                "display_name": "Scratch workspace",
                "status": "healthy",
                "path": "/srv/encodr/scratch",
                "message": "The path is available.",
                "recommended_action": None,
            }
            return {
                "status": "failed",
                "summary": "Storage is not configured yet.",
                "scratch": healthy_path,
                "data_dir": {**healthy_path, "role": "data", "display_name": "Application data", "path": "/srv/encodr/data"},
                "media_mounts": [{
                    **healthy_path,
                    "role": "media_mount",
                    "display_name": "Media library",
                    "status": "failed",
                    "path": "/media",
                    "message": "Media mount not found at /media.",
                    "recommended_action": "Mount your library at /media inside the LXC, then refresh the System page.",
                }],
            }

    monkeypatch.setattr(encodr_cli, "get_system_service_class", lambda: FakeSystemService)

    result = encodr_cli.command_doctor(argparse.Namespace(project_root="."))

    output = capsys.readouterr().out
    assert result == 1
    assert "Storage: failed - Storage is not configured yet." in output
    assert "Media mount not found at /media." in output
    assert "Mount your library at /media inside the LXC" in output


def test_command_doctor_prefers_dockerised_runtime_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(encodr_cli, "load_bundle", lambda _root: fake_bundle())
    monkeypatch.setattr(encodr_cli, "check_api_health", lambda _bundle: {"status": "healthy", "summary": "API responded with ok."})
    monkeypatch.setattr(encodr_cli, "should_use_dockerised_doctor", lambda _root: True)
    monkeypatch.setattr(
        encodr_cli,
        "maybe_collect_dockerised_doctor_payload",
        lambda _root: {
            "runtime": {
                "version": CURRENT_VERSION,
                "status": "healthy",
                "summary": "Runtime health is healthy.",
                "db_reachable": True,
                "schema_reachable": True,
                "first_user_setup_required": True,
            },
            "storage": {
                "status": "healthy",
                "summary": "Configured storage paths are healthy.",
                "scratch": {
                    "role": "scratch",
                    "display_name": "Scratch workspace",
                    "status": "healthy",
                    "path": "/temp/encodr",
                    "message": "The path is available.",
                    "recommended_action": None,
                },
                "data_dir": {
                    "role": "data",
                    "display_name": "Application data",
                    "status": "healthy",
                    "path": "/data",
                    "message": "The path is available.",
                    "recommended_action": None,
                },
                "media_mounts": [{
                    "role": "media_mount",
                    "display_name": "Media library",
                    "status": "healthy",
                    "path": "/media",
                    "message": "The media library path is available.",
                    "recommended_action": None,
                }],
            },
        },
    )

    def fail_if_called(_bundle):
        raise AssertionError("Host database session factory should not be used when dockerised doctor is available.")

    monkeypatch.setattr(encodr_cli, "create_session_factory", fail_if_called)

    result = encodr_cli.command_doctor(argparse.Namespace(project_root="."))

    output = capsys.readouterr().out
    assert result == 0
    assert "Doctor mode: docker-compose/api-container" in output
    assert "Database reachable: yes" in output


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
    assert "prepare_management_cli_runtime" in install_script
    assert "install_startup_service" in install_script
    assert "python3 -m venv" in install_script
    assert "\"psycopg[binary]>=3.1,<4.0\"" in install_script
    assert 'run_with_progress "Launching Docker services" docker compose up -d --build' in install_script
    assert "run_with_progress()" in install_script
    assert "./encodr doctor" in install_script
    assert "DEFAULT_RELEASE_CHANNEL=\"latest\"" in install_script
    assert "docker info >/dev/null 2>&1" in install_script
    assert "Docker daemon is not available" in install_script
    assert "Docker Compose is not available" in install_script
    assert "API health check did not succeed" in install_script
    assert "An existing Encodr installation was found at ${INSTALL_ROOT}." in install_script
    assert "Choose what to do:" in install_script
    assert "Selection [3]:" in install_script
    assert "Existing installation detected. Re-run with one of: --repair, --fresh --force-fresh, --abort-if-exists." in install_script
    assert "INSTALL_TMP_DIR" in install_script
    assert "trap cleanup EXIT" in install_script
    assert "mkdir -p \"${STANDARD_MEDIA_ROOT}\"" not in install_script
    assert "Open Encodr in your browser." in install_script
    assert "Create your first admin user if prompted." in install_script
    assert "Confirm your media library at %s and scratch storage at /temp." in install_script
    assert "encodr mount-setup --validate-only" in install_script
    assert "/etc/systemd/system/encodr.service" in install_script
    assert "ExecStart=/usr/bin/docker compose up -d" in install_script
    assert "ExecStop=/usr/bin/docker compose down" in install_script
    assert "systemctl enable encodr.service" in install_script
    assert "tmp_dir: unbound variable" not in install_script
    assert "trap 'rm -rf \"${tmp_dir}\"' RETURN" not in install_script
    assert 'ENCODR_INSTALL_LIB_ONLY:-0' in install_script
    assert "Stopping existing Docker services" in install_script
    assert "Removing leftover Encodr Docker resources" in install_script
    assert "run_compose_in_install_root()" in install_script
    assert "detect_compose_project_name()" in install_script
    assert "purge_remaining_compose_resources()" in install_script
    assert 'cd "${INSTALL_ROOT}"' in install_script
    assert "down --remove-orphans --volumes --rmi local" in install_script
    assert "docker ps -aq --filter \"label=com.docker.compose.project=${project_name}\"" in install_script
    assert "docker network ls -q --filter \"label=com.docker.compose.project=${project_name}\"" in install_script
    assert "docker volume ls -q --filter \"label=com.docker.compose.project=${project_name}\"" in install_script
    assert "Encodr Docker containers, networks, local images, and Compose volumes" in install_script
    assert "--project-directory" not in install_script


def test_bootstrap_script_creates_runtime_data_and_temp_subdir(repo_root: Path) -> None:
    bootstrap_script = (repo_root / "infra" / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert '$ROOT_DIR/.runtime/data' in bootstrap_script
    assert 'mkdir -p /temp/encodr /media' in bootstrap_script
    assert '$ROOT_DIR/.runtime/temp/encodr' in bootstrap_script
    assert '$ROOT_DIR/.runtime/media' in bootstrap_script


def test_docker_compose_mounts_temp_workspace_into_api_and_worker(repo_root: Path) -> None:
    compose_file = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose_file.count("restart: unless-stopped") == 6
    assert "- ./.runtime/data:/data" in compose_file
    assert "- ${ENCODR_TEMP_HOST_PATH:-/temp}:/temp" in compose_file
    assert "- ./postgres-data:/var/lib/postgresql/data" in compose_file
    assert "- ./redis-data:/data" in compose_file


def test_compose_env_sets_local_media_and_temp_fallbacks(repo_root: Path) -> None:
    env = encodr_cli.compose_env(repo_root)

    assert env["ENCODR_MEDIA_HOST_PATH"] == str(repo_root / ".runtime" / "media")
    assert env["ENCODR_TEMP_HOST_PATH"] == str(repo_root / ".runtime" / "temp")


def test_example_configs_use_temp_for_transcode_scratch(repo_root: Path) -> None:
    app_config = (repo_root / "config" / "app.example.yaml").read_text(encoding="utf-8")
    worker_config = (repo_root / "config" / "workers.example.yaml").read_text(encoding="utf-8")
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    assert "scratch_dir: /temp/encodr" in app_config
    assert "scratch_dir: /temp/encodr" in worker_config
    assert "ENCODR_TEMP_HOST_PATH=/temp" in env_example


def test_local_checkout_uses_compose_override_for_dev_data_volumes(repo_root: Path) -> None:
    command = encodr_cli.compose_command(repo_root, "ps")

    assert command[:6] == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        str(repo_root / "infra" / "compose" / "local.override.yml"),
    ]
    assert command[-1] == "ps"


def test_encodr_wrapper_prefers_managed_cli_venv(repo_root: Path) -> None:
    wrapper = (repo_root / "encodr").read_text(encoding="utf-8")

    assert 'CLI_VENV_PYTHON="${ROOT_DIR}/.runtime/cli-venv/bin/python"' in wrapper
    assert 'if [[ -x "${CLI_VENV_PYTHON}" ]]; then' in wrapper
    assert 'exec "${CLI_VENV_PYTHON}" "${ROOT_DIR}/encodr_cli.py" "$@"' in wrapper
    assert 'exec python3 "${ROOT_DIR}/encodr_cli.py" "$@"' in wrapper


def test_install_script_uses_latest_tagged_release_by_default(repo_root: Path) -> None:
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")

    assert 'ref="$(resolve_latest_release_tag)"' in install_script
    assert 'release_metadata_url="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest"' in install_script
    assert 'selected_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${ref}.tar.gz"' in install_script
    assert 'python3 -c ' in install_script
    assert "json.load(sys.stdin)" in install_script
    assert "Unable to download the Encodr tagged release" in install_script
    assert "archive/refs/heads" not in install_script


def test_install_script_help_mentions_version_override(repo_root: Path) -> None:
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")

    assert "--version REF" in install_script
    assert "--repair" in install_script
    assert "--fresh" in install_script
    assert "--force-fresh" in install_script
    assert "--abort-if-exists" in install_script
    assert "specific tagged release instead of the default latest tagged release" in install_script
    assert "Unknown installer option" in install_script


def test_public_readme_uses_the_remote_installer(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash" in readme
    assert "curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --repair" in readme
    assert "curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --fresh --force-fresh" in readme
    assert "latest tagged release by default" in readme
    assert "encodr update" in readme


def test_install_docs_match_root_friendly_installer_command(repo_root: Path) -> None:
    install_doc = (repo_root / "docs" / "INSTALL.md").read_text(encoding="utf-8")

    assert "curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash" in install_doc
    assert "curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --repair" in install_doc
    assert "curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --fresh --force-fresh" in install_doc
    assert "--version <tag>" in install_doc
    assert "latest tagged release by default" in install_doc


def test_install_script_normalises_host_config_paths_in_env(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PROJECT_NAME=encodr\n"
        "ENCODR_APP_CONFIG_FILE=/config/app.yaml\n"
        "ENCODR_POLICY_CONFIG_FILE=/config/policy.yaml\n"
        "ENCODR_WORKERS_CONFIG_FILE=/config/workers.yaml\n",
        encoding="utf-8",
    )

    result = run_install_shell(
        repo_root,
        (
            f"INSTALL_ROOT='{tmp_path}'; "
            "normalise_host_config_paths_in_env; "
            f"cat '{env_file}'"
        ),
    )

    assert result.returncode == 0
    assert f"ENCODR_APP_CONFIG_FILE={tmp_path}/config/app.yaml" in result.stdout
    assert f"ENCODR_POLICY_CONFIG_FILE={tmp_path}/config/policy.yaml" in result.stdout
    assert f"ENCODR_WORKERS_CONFIG_FILE={tmp_path}/config/workers.yaml" in result.stdout


def test_install_script_help_works_when_piped_into_bash(repo_root: Path) -> None:
    result = subprocess.run(
        ["bash", "-lc", f"cat '{repo_root / 'install.sh'}' | bash -s -- --help"],
        text=True,
        capture_output=True,
        cwd=repo_root,
    )

    assert result.returncode == 0
    assert "Encodr installer" in result.stdout
    assert "Usage:" in result.stdout
    assert "BASH_SOURCE[0]: unbound variable" not in result.stderr


def test_install_script_uses_remote_mode_when_script_path_is_unavailable(
    repo_root: Path,
) -> None:
    result = subprocess.run(
        [
            "bash",
            "-lc",
            f"cat '{repo_root / 'install.sh'}' | ENCODR_INSTALL_ROOT='/tmp/encodr-test-root' bash -s -- --help",
        ],
        text=True,
        capture_output=True,
        cwd=repo_root,
    )

    assert result.returncode == 0
    assert "Encodr installer" in result.stdout


def test_install_script_loads_dotenv_values_with_spaces_safely(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ENCODR_WORKER_AGENT_DISPLAY_NAME=Remote Worker\nAPI_PORT=8000\n# Comment\n",
        encoding="utf-8",
    )

    result = run_install_shell(
        repo_root,
        f"INSTALL_ROOT='{tmp_path}'; load_env; printf '%s|%s\\n' \"$ENCODR_WORKER_AGENT_DISPLAY_NAME\" \"$API_PORT\"",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "Remote Worker|8000"
    assert "command not found" not in result.stderr


def test_existing_install_non_interactive_requires_explicit_flag(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    (tmp_path / ".env").write_text("PROJECT_NAME=encodr\n", encoding="utf-8")

    result = run_install_shell(
        repo_root,
        f"ENCODR_INSTALL_INTERACTIVE=0 INSTALL_ROOT='{tmp_path}' REMOTE_BOOTSTRAP=1 resolve_install_mode",
    )

    assert result.returncode == 1
    assert "Existing installation detected. Re-run with one of: --repair, --fresh --force-fresh, --abort-if-exists." in result.stderr


def test_existing_install_repair_mode_is_selected_explicitly(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    (tmp_path / ".env").write_text("PROJECT_NAME=encodr\n", encoding="utf-8")

    result = run_install_shell(
        repo_root,
        f"ENCODR_INSTALL_INTERACTIVE=0 INSTALL_ROOT='{tmp_path}' REMOTE_BOOTSTRAP=1 INSTALL_MODE_OVERRIDE=repair resolve_install_mode; printf '%s\\n' \"$INSTALL_ACTION\"",
    )

    assert result.returncode == 0
    assert result.stdout.strip().endswith("repair")


def test_existing_install_fresh_mode_requires_force_in_non_interactive_mode(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    (tmp_path / ".env").write_text("PROJECT_NAME=encodr\n", encoding="utf-8")

    result = run_install_shell(
        repo_root,
        f"ENCODR_INSTALL_INTERACTIVE=0 INSTALL_ROOT='{tmp_path}' REMOTE_BOOTSTRAP=1 INSTALL_MODE_OVERRIDE=fresh resolve_install_mode",
    )

    assert result.returncode == 1
    assert "Fresh install is destructive. Re-run with --fresh --force-fresh." in result.stderr


def test_existing_install_fresh_mode_works_with_force_flag(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    (tmp_path / ".env").write_text("PROJECT_NAME=encodr\n", encoding="utf-8")

    result = run_install_shell(
        repo_root,
        f"ENCODR_INSTALL_INTERACTIVE=0 INSTALL_ROOT='{tmp_path}' REMOTE_BOOTSTRAP=1 INSTALL_MODE_OVERRIDE='fresh:confirmed' resolve_install_mode; printf '%s\\n' \"$INSTALL_ACTION\"",
    )

    assert result.returncode == 0
    assert result.stdout.strip().endswith("fresh")


def test_existing_install_interactive_default_aborts_cleanly(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    (tmp_path / ".env").write_text("PROJECT_NAME=encodr\n", encoding="utf-8")

    result = run_install_shell(
        repo_root,
        f"ENCODR_INSTALL_INTERACTIVE=1 INSTALL_ROOT='{tmp_path}' REMOTE_BOOTSTRAP=1 resolve_install_mode",
        input_text="\n",
    )

    assert result.returncode == 0
    assert "Installer aborted. No changes were made." in result.stdout


def test_existing_install_interactive_fresh_requires_delete_confirmation(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    (tmp_path / ".env").write_text("PROJECT_NAME=encodr\n", encoding="utf-8")

    result = run_install_shell(
        repo_root,
        f"ENCODR_INSTALL_INTERACTIVE=1 INSTALL_ROOT='{tmp_path}' REMOTE_BOOTSTRAP=1 resolve_install_mode",
        input_text="2\nno\n",
    )

    assert result.returncode == 0
    assert "Fresh install cancelled. No changes were made." in result.stdout


def test_fresh_install_reset_removes_existing_runtime_state(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    install_root = tmp_path / "encodr"
    (install_root / "config").mkdir(parents=True, exist_ok=True)
    (install_root / "scratch").mkdir(parents=True, exist_ok=True)
    (install_root / ".env").write_text("PROJECT_NAME=encodr\n", encoding="utf-8")

    result = run_install_shell(
        repo_root,
        f"INSTALL_ROOT='{install_root}' REMOTE_BOOTSTRAP=1 perform_fresh_install_reset",
    )

    assert result.returncode == 0
    assert not install_root.exists()


def test_gitignore_excludes_local_ui_workspace(repo_root: Path) -> None:
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")

    assert "dev-local/" in gitignore


def test_workers_example_uses_media_root(repo_root: Path) -> None:
    workers_example = (repo_root / "config" / "workers.example.yaml").read_text(encoding="utf-8")

    assert "- /media" in workers_example


def fake_bundle(*, database_url: str = "sqlite+pysqlite:///:memory:", media_mount: str = "/media"):
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


def run_install_shell(repo_root: Path, shell_body: str, *, input_text: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("ENCODR_INSTALL_INTERACTIVE", "0")
    env["ENCODR_INSTALL_LIB_ONLY"] = "1"
    command = f"source '{repo_root / 'install.sh'}'; {shell_body}"
    return subprocess.run(
        ["bash", "-lc", command],
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        cwd=repo_root,
    )
