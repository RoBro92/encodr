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



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def build_parser() -> argparse.ArgumentParser:
    from cli.system import command_mount_setup, command_version, command_update, command_update_check, command_addhost
    from cli.db import command_reset_admin, command_dev_clear_ui_seed, command_dev_ui, command_dev_seed_ui
    from cli.docker import command_compose_config, command_down, command_stop, command_start, command_logs, command_rebuild, command_restart, command_health
    from cli.health import command_doctor
    parser = argparse.ArgumentParser(prog="encodr", description="Encodr operator management CLI.")
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="Path to the Encodr installation root.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser("version", help="Show the installed Encodr version.")
    version_parser.set_defaults(func=command_version)

    help_parser = subparsers.add_parser("help", help="Show command help.")
    help_parser.set_defaults(func=lambda args: parser.print_help() or 0)

    doctor_parser = subparsers.add_parser("doctor", help="Run local health and configuration checks.")
    doctor_parser.add_argument("scope", nargs="?", choices=["qsv"], help="Run a focused diagnostic scope.")
    doctor_parser.set_defaults(func=command_doctor)

    status_parser = subparsers.add_parser("status", help="Alias for doctor.")
    status_parser.set_defaults(func=command_doctor)

    start_parser = subparsers.add_parser("start", help="Start the local Docker Compose stack from the repo root.")
    start_parser.set_defaults(func=command_start)

    stop_parser = subparsers.add_parser("stop", help="Stop the local Docker Compose stack.")
    stop_parser.set_defaults(func=command_stop)

    restart_parser = subparsers.add_parser("restart", help="Restart the local Docker Compose stack.")
    restart_parser.set_defaults(func=command_restart)

    down_parser = subparsers.add_parser("down", help="Stop and remove local Docker Compose services.")
    down_parser.set_defaults(func=command_down)

    logs_parser = subparsers.add_parser("logs", help="Show local Docker Compose logs.")
    logs_parser.add_argument("--follow", action="store_true", help="Follow the log output.")
    logs_parser.add_argument("--tail", type=int, default=120, help="Number of lines to show per service.")
    logs_parser.set_defaults(func=command_logs)

    compose_config_parser = subparsers.add_parser(
        "compose-config",
        help="Print the managed Docker Compose configuration, including runtime overrides when present.",
    )
    compose_config_parser.set_defaults(func=command_compose_config)

    health_parser = subparsers.add_parser("health", help="Run a quick local stack health check.")
    health_parser.set_defaults(func=command_health)

    rebuild_parser = subparsers.add_parser("rebuild", help="Rebuild and recreate the local Docker Compose stack.")
    rebuild_parser.set_defaults(func=command_rebuild)

    dev_ui_parser = subparsers.add_parser("dev-ui", help="Run the UI in local development mode against the local API.")
    dev_ui_parser.set_defaults(func=command_dev_ui)

    dev_seed_ui_parser = subparsers.add_parser(
        "dev-seed-ui",
        help="Seed local-only UI demo data for design testing.",
    )
    dev_seed_ui_parser.set_defaults(func=command_dev_seed_ui)

    dev_clear_ui_seed_parser = subparsers.add_parser(
        "dev-clear-ui-seed",
        help="Remove local-only UI demo data and restore local worker settings.",
    )
    dev_clear_ui_seed_parser.set_defaults(func=command_dev_clear_ui_seed)

    update_parser = subparsers.add_parser("update", help="Check for updates and optionally apply one.")
    update_parser.add_argument("--apply", action="store_true", help="Download and apply the available update.")
    update_parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt when applying.")
    update_parser.set_defaults(func=command_update)

    update_check_parser = subparsers.add_parser("update-check", help="Check for updates without applying one.")
    update_check_parser.set_defaults(func=command_update_check)

    reset_admin_parser = subparsers.add_parser("reset-admin", help="Create or reset an admin user password.")
    reset_admin_parser.add_argument("--username", default="admin", help="Admin username to create or reset.")
    reset_admin_parser.add_argument(
        "--password",
        help="New password. Deprecated because command-line arguments can expose secrets; use --password-stdin or omit to prompt.",
    )
    reset_admin_parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the new password from stdin for non-interactive automation.",
    )
    reset_admin_parser.set_defaults(func=command_reset_admin)

    mount_parser = subparsers.add_parser("mount-setup", help="Generate and validate storage mount guidance.")
    mount_parser.add_argument("--type", choices=["nfs", "smb"], default="nfs", help="Share type for guidance output.")
    mount_parser.add_argument("--host-source", help="Host-side network share source, for example 10.0.0.10:/share.")
    mount_parser.add_argument("--host-mount", default="/mnt/pve/encodr-media", help="Recommended host-side mount path.")
    mount_parser.add_argument("--container-target", help="Container-visible mount path. Defaults to /media.")
    mount_parser.add_argument("--create-dirs", action="store_true", help="Create the target directory inside the LXC if missing.")
    mount_parser.add_argument("--validate-only", action="store_true", help="Only validate current mounted paths.")
    mount_parser.set_defaults(func=command_mount_setup)

    addhost_parser = subparsers.add_parser(
        "addhost",
        help="Allow an additional UI host name and recreate the stack.",
    )
    addhost_parser.add_argument(
        "host",
        help="Host name to allow, for example encodr.example.com.",
    )
    addhost_parser.set_defaults(func=command_addhost)

    return parser


def print_container_command_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)


def print_api_container_command_error(
    operation: str,
    exec_result: subprocess.CompletedProcess[str],
    run_result: subprocess.CompletedProcess[str],
    *,
    sensitive_values: list[str] | None = None,
) -> None:
    print(f"Unable to run {operation} inside the API container.")
    print("Confirm Docker is running and the Encodr stack/API image exists, then run: docker compose up -d --build")
    details = first_nonempty_line(
        run_result.stderr,
        run_result.stdout,
        exec_result.stderr,
        exec_result.stdout,
        sensitive_values=sensitive_values or [],
    )
    if details:
        print(f"Docker reported: {details}")


def first_nonempty_line(*values: str | None, sensitive_values: list[str] | None = None) -> str | None:
    for value in values:
        if not value:
            continue
        for line in value.splitlines():
            stripped = line.strip()
            if stripped:
                return redact_sensitive_text(stripped, sensitive_values=sensitive_values or [])
    return None


def redact_sensitive_text(value: str, *, sensitive_values: list[str]) -> str:
    redacted = value
    for secret in sensitive_values:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(
        r"([A-Za-z][A-Za-z0-9+.-]*://)([^@\s/]*):([^@\s]*)(@)",
        lambda match: f"{match.group(1)}{match.group(2) or '[redacted]'}:[redacted]{match.group(4)}",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 [redacted]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([?&](?:password|passwd|secret|token|api[_-]?key|authorization|pairing)=)[^&#\s]+",
        r"\1[redacted]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|KEY)[A-Z0-9_]*=)([^\s]+)",
        r"\1[redacted]",
        redacted,
    )
    return redacted


def should_use_dockerised_doctor(project_root: Path) -> bool:
    from cli.docker import compose_env, compose_command
    if not (project_root / "docker-compose.yml").exists():
        return False

    compose_version = subprocess.run(
        compose_command(project_root, "version"),
        cwd=project_root,
        env=compose_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return compose_version.returncode == 0


def docker_compose_exec_api_python(project_root: Path, script: str) -> str | None:
    from cli.docker import compose_env, compose_command
    result = subprocess.run(
        compose_command(project_root, "exec", "-T", "api", "python", "-c", script),
        cwd=project_root,
        env=compose_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def docker_compose_run_api_python(project_root: Path, script: str) -> str | None:
    from cli.docker import compose_env, compose_command
    datastore_result = subprocess.run(
        compose_command(project_root, "up", "-d", "postgres", "redis"),
        cwd=project_root,
        env=compose_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if datastore_result.returncode != 0:
        return None

    result = subprocess.run(
        compose_command(project_root, "run", "--rm", "--no-deps", "-T", "api", "python", "-c", script),
        cwd=project_root,
        env=compose_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def sync_release_tree(*, source_root: Path, target_root: Path) -> None:
    excluded_names = {
        ".dockerignore",
        ".git",
        ".github",
        ".env",
        ".runtime",
        "CHANGELOG.md",
        "Makefile",
        "README.md",
        "docs",
        "node_modules",
        "postgres-data",
        "pytest.ini",
        "redis-data",
        "scratch",
        "tests",
        "__pycache__",
    }
    preserved_config_files = {
        target_root / "config" / "app.yaml",
        target_root / "config" / "policy.yaml",
        target_root / "config" / "workers.yaml",
    }

    for path in source_root.rglob("*"):
        relative = path.relative_to(source_root)
        if any(part in excluded_names for part in relative.parts):
            continue
        destination = target_root / relative
        if destination in preserved_config_files:
            continue
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def detect_restart_environment() -> str:
    runtime_container = Path("/run/systemd/container")
    if runtime_container.exists():
        container_name = runtime_container.read_text(encoding="utf-8").strip().lower()
        if container_name == "lxc":
            return "lxc"
        if container_name:
            return "container"

    environ_path = Path("/proc/1/environ")
    if environ_path.exists():
        try:
            raw = environ_path.read_bytes().decode("utf-8", errors="ignore")
        except OSError:
            raw = ""
        if "container=lxc" in raw:
            return "lxc"
        if "container=" in raw:
            return "container"

    return "system"


