from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
for extra_path in (
    REPO_ROOT / "packages" / "core",
    REPO_ROOT / "packages" / "shared",
    REPO_ROOT / "packages" / "db",
    REPO_ROOT / "apps" / "api",
):
    path_text = str(extra_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from encodr_core.config import ConfigBundle, load_config_bundle
from encodr_db.models import AuditEventType, AuditOutcome, UserRole
from encodr_db.repositories import AuditEventRepository, UserRepository
from encodr_shared import (
    UpdateCheckSettings,
    UpdateChecker,
    detect_ffmpeg_hwaccels,
    discover_runtime_devices,
    probe_binary,
    probe_intel_qsv,
    probe_intel_vaapi,
    read_version,
    resolve_backend_runtime_status,
)


RESET_ADMIN_CONTAINER_SCRIPT = r"""
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import PasswordHashService
from encodr_core.config import load_config_bundle
from encodr_db.models import AuditEventType, AuditOutcome, UserRole
from encodr_db.repositories import AuditEventRepository, UserRepository

payload = json.loads(sys.stdin.read())
username = str(payload["username"])
password = str(payload["password"])

if len(password) < 8:
    print("Password must be at least 8 characters.")
    raise SystemExit(1)

bundle = load_config_bundle()
engine = create_engine(bundle.app.database.dsn, future=True)
Session = sessionmaker(engine, future=True, expire_on_commit=False)
password_hasher = PasswordHashService(bundle.app.auth.password_hash_scheme)

with Session() as session:
    users = UserRepository(session)
    user = users.get_by_username(username)
    created = False
    if user is None:
        if users.any_users_exist():
            print(f"Admin user '{username}' does not exist.")
            raise SystemExit(1)
        user = users.create_user(
            username=username,
            password_hash=password_hasher.hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
            is_bootstrap_admin=True,
        )
        created = True
    else:
        user.password_hash = password_hasher.hash_password(password)
        user.role = UserRole.ADMIN
        user.is_active = True
        session.flush()

    AuditEventRepository(session).add_event(
        event_type=AuditEventType.ADMIN_RESET,
        outcome=AuditOutcome.SUCCESS,
        user=user,
        details={"created": created, "via": "cli"},
    )
    session.commit()

print(f"Admin user '{username}' {'created' if created else 'updated'} successfully.")
""".strip()


DEV_SEED_UI_CONTAINER_SCRIPT = r"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from encodr_core.config import load_config_bundle
from encodr_db.dev_seed_ui import seed_ui_demo_data

bundle = load_config_bundle()
engine = create_engine(bundle.app.database.dsn, future=True)
Session = sessionmaker(engine, future=True, expire_on_commit=False)
summary = seed_ui_demo_data(Session, bundle)
print("Seeded Encodr UI demo data. This command is development/demo-only and never runs automatically.")
print(f"Worker: {summary.worker_display_name} ({summary.worker_key})")
print(f"Demo media root: {summary.demo_media_root}")
print(f"Tracked files: {summary.tracked_files_seeded}")
print(f"Jobs: {summary.jobs_seeded}")
print(f"Review items: {summary.review_items_seeded}")
print("Run './encodr dev-clear-ui-seed' to remove the demo records.")
""".strip()


DEV_CLEAR_UI_SEED_CONTAINER_SCRIPT = r"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from encodr_core.config import load_config_bundle
from encodr_db.dev_seed_ui import clear_ui_demo_data

bundle = load_config_bundle()
engine = create_engine(bundle.app.database.dsn, future=True)
Session = sessionmaker(engine, future=True, expire_on_commit=False)
summary = clear_ui_demo_data(Session, bundle)
print("Cleared Encodr UI demo data.")
print(f"Demo media root: {summary.demo_media_root}")
print(f"Tracked files removed: {summary.tracked_files_removed}")
print(f"Jobs removed: {summary.jobs_removed}")
print(f"Review items removed: {summary.review_items_removed}")
if summary.worker_restored:
    print("Local worker settings restored to their pre-demo values.")
elif summary.worker_removed:
    print("Demo-created local worker removed.")
else:
    print("No demo local worker settings were found.")
""".strip()


def command_start(args: argparse.Namespace) -> int:
    from cli.utils import bootstrap_repo, ensure_local_storage_mounts
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    ensure_local_storage_mounts(project_root)
    ensure_runtime_compose_override(project_root)
    print("Starting Encodr locally with Docker Compose...")
    return run_compose(args, ["up", "-d", "--build"])


def command_stop(args: argparse.Namespace) -> int:
    print("Stopping the local Encodr stack...")
    return run_compose(args, ["stop"])


def command_restart(args: argparse.Namespace) -> int:
    from cli.utils import bootstrap_repo, ensure_local_storage_mounts
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    ensure_local_storage_mounts(project_root)
    ensure_runtime_compose_override(project_root)
    print("Restarting the local Encodr stack...")
    return run_compose(args, ["restart"])


def command_down(args: argparse.Namespace) -> int:
    print("Stopping and removing local Encodr containers...")
    return run_compose(args, ["down", "--remove-orphans"])


def command_logs(args: argparse.Namespace) -> int:
    command = ["logs", f"--tail={args.tail}"]
    if args.follow:
        command.append("--follow")
    return run_compose(args, command)


def command_compose_config(args: argparse.Namespace) -> int:
    from cli.utils import ensure_local_storage_mounts
    project_root = Path(args.project_root).resolve()
    ensure_local_storage_mounts(project_root)
    ensure_runtime_compose_override(project_root)
    result = subprocess.run(
        compose_command(project_root, "config"),
        cwd=project_root,
        env=compose_env(project_root),
        check=False,
    )
    return int(result.returncode)


def command_health(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle, bootstrap_repo
    from cli.health import check_url
    from cli.system import local_ui_health_url
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    ensure_runtime_compose_override(project_root)
    bundle = load_bundle(project_root)
    compose_result = subprocess.run(
        compose_command(project_root, "ps"),
        cwd=project_root,
        env=compose_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )

    api_status = check_url(f"http://127.0.0.1:{bundle.app.api.port}{bundle.app.api.base_path}/health")
    local_ui_url = local_ui_health_url(project_root)
    ui_status = check_url(local_ui_url)

    print("Local stack health")
    print("------------------")
    print(f"API: {api_status['status']} - {api_status['summary']}")
    print(f"UI: {ui_status['status']} - {ui_status['summary']}")
    print(f"API URL: http://127.0.0.1:{bundle.app.api.port}{bundle.app.api.base_path}/health")
    print(f"Local UI URL: {local_ui_url}")
    print(f"Public UI URL: {bundle.app.ui.public_url}")
    print("\nDocker Compose services:")
    print(compose_result.stdout.strip() or compose_result.stderr.strip() or "(no compose output)")

    if api_status["status"] != "healthy" or ui_status["status"] != "healthy" or compose_result.returncode != 0:
        print("\nNext steps:")
        print("  ./encodr logs")
        print("  ./encodr doctor")
        print("  docker compose ps")
        return 1

    return 0


def command_rebuild(args: argparse.Namespace) -> int:
    from cli.utils import bootstrap_repo, ensure_local_storage_mounts
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    ensure_local_storage_mounts(project_root)
    ensure_runtime_compose_override(project_root)
    print("Rebuilding and recreating the local Encodr stack...")
    return run_compose(args, ["up", "-d", "--build", "--force-recreate"])


def run_compose(args: argparse.Namespace, compose_args: list[str]) -> int:
    project_root = Path(args.project_root).resolve()
    result = subprocess.run(
        compose_command(project_root, *compose_args),
        cwd=project_root,
        env=compose_env(project_root),
        check=False,
    )
    return int(result.returncode)


def compose_env(project_root: Path) -> dict[str, str]:
    from cli.system import read_env_value
    from cli.utils import ensure_local_storage_mounts, repair_runtime_mount_permissions
    env = os.environ.copy()
    media_root, temp_root = ensure_local_storage_mounts(project_root)
    runtime_uid, runtime_gid = runtime_container_ids(project_root, env)
    env.setdefault("ENCODR_RUNTIME_UID", str(runtime_uid))
    env.setdefault("ENCODR_RUNTIME_GID", str(runtime_gid))
    env.setdefault("ENCODR_MEDIA_HOST_PATH", read_env_value(project_root / ".env", "ENCODR_MEDIA_HOST_PATH") or str(media_root))
    env.setdefault("ENCODR_TEMP_HOST_PATH", read_env_value(project_root / ".env", "ENCODR_TEMP_HOST_PATH") or str(temp_root))
    repair_runtime_mount_permissions(project_root, env=env, uid=runtime_uid, gid=runtime_gid)
    return env


def compose_command(project_root: Path, *compose_args: str) -> list[str]:
    ensure_runtime_compose_override(project_root)
    command = ["docker", "compose"]
    local_override = project_root / "infra" / "compose" / "local.override.yml"
    runtime_override = project_root / ".runtime" / "compose.runtime.yml"
    command.extend(["-f", "docker-compose.yml"])
    if compose_uses_local_dev_datastore_ports(project_root):
        command.extend(["-f", str(local_override)])
    if runtime_override.exists():
        command.extend(["-f", str(runtime_override)])
    command.extend(compose_args)
    return command


def compose_uses_local_dev_datastore_ports(project_root: Path) -> bool:
    from cli.system import read_env_value
    environment = (read_env_value(project_root / ".env", "ENCODR_ENV") or "").strip().strip("\"'").lower()
    return (
        (project_root / ".git").exists()
        and (project_root / "infra" / "compose" / "local.override.yml").exists()
        and environment == "development"
    )


def runtime_container_ids(project_root: Path, env: dict[str, str]) -> tuple[int, int]:
    from cli.system import read_env_value
    from cli.utils import parse_positive_int
    env_path = project_root / ".env"
    uid = parse_positive_int(env.get("ENCODR_RUNTIME_UID") or read_env_value(env_path, "ENCODR_RUNTIME_UID"), 10001)
    gid = parse_positive_int(env.get("ENCODR_RUNTIME_GID") or read_env_value(env_path, "ENCODR_RUNTIME_GID"), 10001)
    return uid, gid


def ensure_runtime_compose_override(project_root: Path) -> None:
    generator = project_root / "infra" / "scripts" / "generate_runtime_compose.py"
    if not generator.exists():
        return
    subprocess.run(
        [sys.executable, str(generator), "--project-root", str(project_root)],
        cwd=project_root,
        check=True,
    )


