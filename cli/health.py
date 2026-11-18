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


def command_doctor(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle, get_system_service_class
    from cli.db import create_session_factory, should_run_db_command_in_api_container
    if getattr(args, "scope", None) == "qsv":
        return command_doctor_qsv(args)

    project_root = Path(args.project_root).resolve()
    bundle = load_bundle(project_root)
    api_health = check_api_health(bundle)
    doctor_mode = "host-direct"

    dockerised_payload = maybe_collect_dockerised_doctor_payload(project_root)
    if dockerised_payload is not None:
        runtime = dockerised_payload["runtime"]
        storage = dockerised_payload["storage"]
        doctor_mode = "docker-compose/api-container"
    elif should_run_db_command_in_api_container(bundle, project_root):
        system_service_class = get_system_service_class()
        system = system_service_class(
            config_bundle=bundle,
            session_factory=None,
            app_version=read_version(project_root),
        )
        runtime = system.runtime_status()
        storage = system.storage_status()
        doctor_mode = "docker-compose/api-container-unavailable"
    else:
        session_factory = create_session_factory(bundle)
        system_service_class = get_system_service_class()
        system = system_service_class(
            config_bundle=bundle,
            session_factory=session_factory,
            app_version=read_version(project_root),
        )
        runtime = system.runtime_status()
        storage = system.storage_status()

    print(f"Version: {runtime['version']}")
    print(f"Doctor mode: {doctor_mode}")
    print(f"Runtime: {runtime['status']} - {runtime['summary']}")
    print(f"API health: {api_health['status']} - {api_health['summary']}")
    print(f"Database reachable: {'yes' if runtime['db_reachable'] else 'no'}")
    print(f"Schema reachable: {'yes' if runtime['schema_reachable'] else 'no'}")
    print(f"First-user setup required: {'yes' if runtime['first_user_setup_required'] else 'no'}")
    print(f"Storage: {storage['status']} - {storage['summary']}")
    for item in [storage["scratch"], storage["data_dir"], *storage["media_mounts"]]:
        print(f"  - {item.get('display_name', item['role'])}: {item['status']} ({item['path']})")
        if item.get("message"):
            print(f"      {item['message']}")
        if item.get("recommended_action"):
            print(f"      Next: {item['recommended_action']}")

    failed = any(
        [
            runtime["status"] == "failed",
            storage["status"] == "failed",
            api_health["status"] == "failed",
        ]
    )
    return 1 if failed else 0


def command_doctor_qsv(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle
    project_root = Path(args.project_root).resolve()
    bundle = load_bundle(project_root)
    ffmpeg_path = bundle.app.media.ffmpeg_path
    ffmpeg = probe_binary(ffmpeg_path)
    devices = discover_runtime_devices()
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path)
    qsv = probe_intel_qsv(ffmpeg_path)
    vaapi = probe_intel_vaapi(ffmpeg_path)
    intel_probe_payload = {
        "backend": "intel_igpu",
        "preference_key": "prefer_intel_igpu",
        "preference_keys": ["prefer_intel_igpu", "intel_auto", "intel_qsv", "intel_vaapi", "qsv", "vaapi", "auto"],
        "usable_by_ffmpeg": qsv.usable or vaapi.usable,
        "message": "Intel backend diagnostic",
        "details": {
            "qsv": qsv.details | {"usable": qsv.usable, "message": qsv.message, "status": qsv.status},
            "vaapi": vaapi.details | {"usable": vaapi.usable, "message": vaapi.message, "status": vaapi.status},
            "qsv_unavailable_reason": None if qsv.usable else qsv.details.get("reason_unavailable") or qsv.message,
        },
    }
    recommendation = resolve_backend_runtime_status(
        "intel_auto",
        [intel_probe_payload],
        allow_cpu_fallback=True,
        cpu_available=ffmpeg.discoverable,
    )

    print("Intel QSV diagnostic")
    print("--------------------")
    print(f"FFmpeg: {ffmpeg.resolved_path or ffmpeg.configured_path} ({ffmpeg.status})")
    print(f"FFmpeg hwaccels: {', '.join(hwaccels) if hwaccels else 'not reported'}")
    print("FFmpeg build flags:")
    for flag in ffmpeg_build_flags(ffmpeg.resolved_path or str(ffmpeg_path), ["--enable-libvpl", "--enable-libmfx", "--enable-vaapi"]):
        print(f"  - {flag}")
    print("oneVPL/MFX libraries:")
    for line in qsv_runtime_libraries():
        print(f"  - {line}")
    print("/dev/dri devices:")
    intel_devices = [item for item in devices if str(item.get("path", "")).startswith("/dev/dri")]
    if not intel_devices:
        print("  - none visible")
    for item in intel_devices:
        print(
            "  - "
            f"{item.get('path')} "
            f"{item.get('status')} "
            f"vendor={item.get('vendor_name') or item.get('vendor_id') or 'unknown'} "
            f"readable={item.get('readable')} writable={item.get('writable')}"
        )

    print(f"VAAPI smoke: {vaapi.status} - {vaapi.message}")
    if vaapi.details.get("reason_unavailable"):
        print(f"  reason: {vaapi.details['reason_unavailable']}")
    print(f"QSV smoke: {qsv.status} - {qsv.message}")
    if qsv.details.get("reason_unavailable"):
        print(f"  reason: {qsv.details['reason_unavailable']}")
    attempts = qsv.details.get("ffmpeg_smoke_attempts")
    if isinstance(attempts, list) and attempts:
        print("QSV smoke commands:")
        for attempt in attempts:
            if isinstance(attempt, dict):
                print(f"  - {attempt.get('init_method')}: {attempt.get('command')}")
                if attempt.get("stderr"):
                    print(f"    stderr: {attempt['stderr']}")

    selected = recommendation.get("selected_backend") or "none"
    print(f"Recommended backend: {selected}")
    if recommendation.get("fallback_reason"):
        print(f"Fallback reason: {recommendation['fallback_reason']}")
    return 0 if qsv.usable or vaapi.usable else 1


def check_api_health(bundle: ConfigBundle) -> dict[str, str]:
    url = f"http://127.0.0.1:{bundle.app.api.port}{bundle.app.api.base_path}/health"
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return {"status": "healthy", "summary": f"API responded with {payload.get('status', 'ok')}."}
    except (URLError, OSError, json.JSONDecodeError) as error:
        return {"status": "failed", "summary": str(error)}


def maybe_collect_dockerised_doctor_payload(project_root: Path) -> dict[str, object] | None:
    from cli.main import should_use_dockerised_doctor, docker_compose_exec_api_python, docker_compose_run_api_python
    if not should_use_dockerised_doctor(project_root):
        return None

    diagnostics_script = """
import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from encodr_core.config import load_config_bundle
from encodr_shared import read_version
from app.services.system import SystemService

project_root = Path('/app')
bundle = load_config_bundle(project_root=project_root)
engine = create_engine(bundle.app.database.dsn, future=True)
session_factory = sessionmaker(engine, future=True, expire_on_commit=False)
system = SystemService(
    config_bundle=bundle,
    session_factory=session_factory,
    app_version=read_version(project_root),
)
print(json.dumps(
    {
        "runtime": system.runtime_status(),
        "storage": system.storage_status(),
    },
    default=str,
))
""".strip()
    diagnostics = docker_compose_exec_api_python(project_root, diagnostics_script)
    if diagnostics is None:
        diagnostics = docker_compose_run_api_python(project_root, diagnostics_script)

    if diagnostics is None:
        return None

    try:
        payload = json.loads(diagnostics)
    except json.JSONDecodeError:
        return None

    runtime = payload.get("runtime")
    storage = payload.get("storage")
    if not isinstance(runtime, dict) or not isinstance(storage, dict):
        return None
    return {"runtime": runtime, "storage": storage}


def run_updated_doctor(project_root: Path) -> int:
    cli_script = project_root / "encodr"
    if cli_script.exists():
        command = [str(cli_script), "doctor"]
    else:
        command = [
            sys.executable,
            str(project_root / "encodr_cli.py"),
            "--project-root",
            str(project_root),
            "doctor",
        ]

    result = subprocess.run(command, cwd=project_root, check=False)
    return int(result.returncode)


def ffmpeg_build_flags(ffmpeg_path: str, interesting_flags: list[str]) -> list[str]:
    try:
        completed = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-buildconf"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return [f"unable to read build configuration: {error}"]
    output = f"{completed.stdout}\n{completed.stderr}"
    flags = []
    for flag in interesting_flags:
        if flag in output:
            flags.append(flag)
    if not flags:
        return ["none of --enable-libvpl, --enable-libmfx, or --enable-vaapi were reported"]
    return flags


def qsv_runtime_libraries() -> list[str]:
    if os.name == "nt":
        return ["Windows QSV runtime discovery is not implemented by this CLI."]
    ldconfig_path = shutil.which("ldconfig")
    if not ldconfig_path:
        return ["ldconfig is not available; cannot list libvpl/libmfx."]
    try:
        completed = subprocess.run(
            [ldconfig_path, "-p"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return [f"unable to query runtime libraries: {error}"]
    matches = [
        line.strip()
        for line in completed.stdout.splitlines()
        if "libvpl" in line.lower() or "libmfx" in line.lower()
    ]
    return matches or ["libvpl/libmfx not reported by ldconfig"]


def check_url(url: str) -> dict[str, str]:
    try:
        with urlopen(url, timeout=5) as response:
            return {
                "status": "healthy",
                "summary": f"HTTP {response.status}",
            }
    except URLError as exc:
        return {
            "status": "failed",
            "summary": str(exc.reason),
        }


