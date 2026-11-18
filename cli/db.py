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


def command_dev_ui(args: argparse.Namespace) -> int:
    from cli.utils import bootstrap_repo
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    env = os.environ.copy()
    env.setdefault("ENCODR_UI_API_PROXY_TARGET", "http://127.0.0.1:8000")
    ui_root = project_root / "apps" / "ui"
    if not (ui_root / "node_modules").exists():
        subprocess.run(["npm", "install"], cwd=ui_root, env=env, check=True)
    print("Starting the UI development server on http://127.0.0.1:5173 ...")
    subprocess.run(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], cwd=ui_root, env=env, check=True)
    return 0


def command_dev_seed_ui(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle
    project_root = Path(args.project_root).resolve()
    bundle = load_bundle(project_root)
    if should_run_db_command_in_api_container(bundle, project_root):
        return run_api_container_python(
            project_root,
            DEV_SEED_UI_CONTAINER_SCRIPT,
            operation="dev-seed-ui",
        )

    session_factory = create_local_cli_session_factory(bundle, project_root)
    from encodr_db.dev_seed_ui import seed_ui_demo_data

    summary = seed_ui_demo_data(session_factory, bundle)
    print("Seeded Encodr UI demo data. This command is development/demo-only and never runs automatically.")
    print(f"Worker: {summary.worker_display_name} ({summary.worker_key})")
    print(f"Demo media root: {summary.demo_media_root}")
    print(f"Tracked files: {summary.tracked_files_seeded}")
    print(f"Jobs: {summary.jobs_seeded}")
    print(f"Review items: {summary.review_items_seeded}")
    print("Run './encodr dev-clear-ui-seed' to remove the demo records.")
    return 0


def command_dev_clear_ui_seed(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle
    project_root = Path(args.project_root).resolve()
    bundle = load_bundle(project_root)
    if should_run_db_command_in_api_container(bundle, project_root):
        return run_api_container_python(
            project_root,
            DEV_CLEAR_UI_SEED_CONTAINER_SCRIPT,
            operation="dev-clear-ui-seed",
        )

    session_factory = create_local_cli_session_factory(bundle, project_root)
    from encodr_db.dev_seed_ui import clear_ui_demo_data

    summary = clear_ui_demo_data(session_factory, bundle)
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
    return 0


def command_reset_admin(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle, get_password_hash_service_class
    project_root = Path(args.project_root).resolve()
    bundle = load_bundle(project_root)
    password = read_reset_admin_password(args)
    if password is None:
        return 1
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return 1

    if should_run_db_command_in_api_container(bundle, project_root):
        return run_reset_admin_in_api_container(
            project_root,
            username=args.username,
            password=password,
        )

    session_factory = create_local_cli_session_factory(bundle, project_root)
    password_hash_service_class = get_password_hash_service_class()
    password_hasher = password_hash_service_class(bundle.app.auth.password_hash_scheme)
    with session_factory() as session:
        users = UserRepository(session)
        user = users.get_by_username(args.username)
        created = False
        if user is None:
            if users.any_users_exist():
                print(f"Admin user '{args.username}' does not exist.")
                return 1
            user = users.create_user(
                username=args.username,
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

    print(f"Admin user '{args.username}' {'created' if created else 'updated'} successfully.")
    return 0


def read_reset_admin_password(args: argparse.Namespace) -> str | None:
    password_arg = getattr(args, "password", None)
    password_stdin = bool(getattr(args, "password_stdin", False))
    if password_arg and password_stdin:
        print("Use either --password or --password-stdin, not both.")
        return None
    if password_stdin:
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            print("No password was read from stdin.")
            return None
        return password
    if password_arg:
        print(
            "Warning: --password can expose secrets in shell history and process listings; "
            "use --password-stdin or omit it to prompt securely.",
            file=sys.stderr,
        )
        return password_arg
    return getpass.getpass("New admin password: ")


def run_reset_admin_in_api_container(project_root: Path, *, username: str, password: str) -> int:
    payload = json.dumps({"username": username, "password": password})
    return run_api_container_python(
        project_root,
        RESET_ADMIN_CONTAINER_SCRIPT,
        operation="reset-admin",
        input_text=payload,
        sensitive_values=[password],
    )


def create_session_factory(bundle: ConfigBundle) -> sessionmaker:
    engine = create_engine(bundle.app.database.dsn, future=True)
    return sessionmaker(engine, future=True, expire_on_commit=False)


def create_local_cli_session_factory(bundle: ConfigBundle, project_root: Path) -> sessionmaker:
    dsn = host_reachable_database_dsn(str(bundle.app.database.dsn), project_root)
    engine = create_engine(dsn, future=True)
    return sessionmaker(engine, future=True, expire_on_commit=False)


def host_reachable_database_dsn(dsn: str, project_root: Path) -> str:
    from cli.utils import running_inside_container
    from cli.system import read_env_value
    from cli.docker import compose_uses_local_dev_datastore_ports
    parsed = urlsplit(dsn)
    if parsed.hostname != "postgres" or running_inside_container():
        return dsn
    if not compose_uses_local_dev_datastore_ports(project_root):
        return dsn

    host_port = read_env_value(project_root / ".env", "POSTGRES_PORT") or str(parsed.port or 5432)
    credentials = ""
    if "@" in parsed.netloc:
        credentials = f"{parsed.netloc.rsplit('@', maxsplit=1)[0]}@"
    return parsed._replace(netloc=f"{credentials}127.0.0.1:{host_port}").geturl()


def database_dsn_targets_compose_postgres(dsn: str) -> bool:
    try:
        parsed = urlsplit(dsn)
    except ValueError:
        return False
    return parsed.hostname == "postgres"


def should_run_db_command_in_api_container(bundle: ConfigBundle, project_root: Path) -> bool:
    from cli.utils import running_inside_container
    from cli.docker import compose_uses_local_dev_datastore_ports
    return (
        database_dsn_targets_compose_postgres(str(bundle.app.database.dsn))
        and not running_inside_container()
        and not compose_uses_local_dev_datastore_ports(project_root)
    )


def run_api_container_python(
    project_root: Path,
    script: str,
    *,
    operation: str,
    input_text: str | None = None,
    sensitive_values: list[str] | None = None,
) -> int:
    from cli.docker import compose_env, compose_command
    from cli.main import first_nonempty_line, print_container_command_output, print_api_container_command_error
    secrets = sensitive_values or []
    datastore_result = subprocess.run(
        compose_command(project_root, "up", "-d", "postgres", "redis"),
        cwd=project_root,
        env=compose_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if datastore_result.returncode != 0:
        print(f"Unable to prepare private datastore services for {operation}.")
        print("Confirm Docker is running, then run: docker compose up -d postgres redis")
        details = first_nonempty_line(datastore_result.stderr, datastore_result.stdout, sensitive_values=secrets)
        if details:
            print(f"Docker reported: {details}")
        return int(datastore_result.returncode or 1)

    run_command = compose_command(project_root, "run", "--rm", "--no-deps", "-T", "api", "python", "-c", script)
    run_result = subprocess.run(
        run_command,
        cwd=project_root,
        env=compose_env(project_root),
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if run_result.returncode == 0:
        print_container_command_output(run_result)
        return 0

    exec_command = compose_command(project_root, "exec", "-T", "api", "python", "-c", script)
    exec_result = subprocess.run(
        exec_command,
        cwd=project_root,
        env=compose_env(project_root),
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if exec_result.returncode == 0:
        print_container_command_output(exec_result)
        return 0

    print_api_container_command_error(operation, exec_result, run_result, sensitive_values=secrets)
    return int(run_result.returncode or exec_result.returncode or 1)


