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


def load_bundle(project_root: str | Path) -> ConfigBundle:
    return load_config_bundle(project_root=Path(project_root).resolve())


def bootstrap_repo(project_root: Path) -> None:
    subprocess.run(["bash", "./infra/scripts/bootstrap.sh"], cwd=project_root, check=True)


def ensure_local_storage_mounts(project_root: Path) -> tuple[Path, Path]:
    media_root = project_root / ".runtime" / "media"
    temp_root = project_root / ".runtime" / "temp"
    media_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    return media_root, temp_root


def parse_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def repair_runtime_mount_permissions(project_root: Path, *, env: dict[str, str], uid: int, gid: int) -> None:
    if getattr(os, "geteuid", lambda: -1)() != 0:
        return

    runtime_root = project_root / ".runtime"
    logs_root = runtime_root / "data" / "logs"
    candidate_roots = [
        runtime_root / "data",
        logs_root,
        Path(env["ENCODR_TEMP_HOST_PATH"]).expanduser(),
    ]
    media_path = Path(env["ENCODR_MEDIA_HOST_PATH"]).expanduser()
    try:
        media_path.relative_to(runtime_root)
    except ValueError:
        pass
    else:
        candidate_roots.append(media_path)

    for root in candidate_roots:
        repair_runtime_tree_owner(root, uid=uid, gid=gid)


def repair_runtime_tree_owner(root: Path, *, uid: int, gid: int) -> None:
    if path_has_symlink_component(root):
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    if path_has_symlink_component(root):
        return
    for path in runtime_tree_paths_without_symlink_traversal(root):
        repair_path_owner(path, uid=uid, gid=gid)


def path_has_symlink_component(path: Path) -> bool:
    for candidate in [path, *path.parents]:
        try:
            if candidate.is_symlink():
                return True
        except OSError:
            return True
    return False


def runtime_tree_paths_without_symlink_traversal(root: Path):
    yield root
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for dirname in list(dirnames):
            child = Path(dirpath) / dirname
            yield child
            if child.is_symlink():
                dirnames.remove(dirname)
        for filename in filenames:
            yield Path(dirpath) / filename


def repair_path_owner(path: Path, *, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid, follow_symlinks=False)
    except OSError:
        return


def running_inside_container() -> bool:
    return Path("/.dockerenv").exists()


def get_system_service_class():
    module = importlib.import_module("app.services.system")
    return module.SystemService


def get_password_hash_service_class():
    module = importlib.import_module("app.core.security")
    return module.PasswordHashService


