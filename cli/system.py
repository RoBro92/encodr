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


def command_version(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle
    bundle = load_bundle(args.project_root)
    print(f"Encodr {read_version(Path(args.project_root))}")
    print(f"Environment: {bundle.app.environment.value}")
    print(f"API base path: {bundle.app.api.base_path}")
    print(f"UI URL: {bundle.app.ui.public_url}")
    return 0


def command_update(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle
    from cli.docker import ensure_runtime_compose_override, compose_env, compose_command
    from cli.health import run_updated_doctor
    project_root = Path(args.project_root).resolve()
    bundle = load_bundle(project_root)
    checker = build_update_checker(bundle)
    status = checker.check_now()
    print_update_status(status)

    if not status.update_available:
        return 0 if status.status != "error" else 1

    if not args.apply:
        print("Update available. Re-run with --apply to download and install it.")
        return 0

    if not status.download_url:
        print("No download URL was provided by the update metadata source.")
        return 1

    if not args.yes:
        answer = input(f"Apply update to {status.latest_version}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Update cancelled.")
            return 0

    apply_archive_update(project_root=project_root, download_url=status.download_url)
    ensure_runtime_compose_override(project_root)
    subprocess.run(
        compose_command(project_root, "up", "-d", "--build"),
        cwd=project_root,
        env=compose_env(project_root),
        check=True,
    )
    doctor_result = run_updated_doctor(project_root)
    prompt_for_restart_after_update()
    return doctor_result


def command_update_check(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle
    checker = build_update_checker(load_bundle(args.project_root))
    status = checker.check_now()
    print_update_status(status)
    return 0 if status.status != "error" else 1


def command_mount_setup(args: argparse.Namespace) -> int:
    from cli.utils import load_bundle
    bundle = load_bundle(args.project_root)
    container_target = args.container_target or (
        bundle.workers.local.media_mounts[0].as_posix()
        if bundle.workers.local.media_mounts
        else "/media"
    )
    target_path = Path(container_target)

    if args.create_dirs:
        target_path.mkdir(parents=True, exist_ok=True)

    readable = target_path.exists() and os.access(target_path, os.R_OK)
    writable = target_path.exists() and os.access(target_path, os.W_OK)
    entry_count = None
    if target_path.exists() and target_path.is_dir():
        try:
            entry_count = sum(1 for _ in target_path.iterdir())
        except OSError:
            entry_count = None

    print("Recommended model: mount the share on the Proxmox host, bind-mount it into the LXC, then bind it into Docker inside the LXC.")
    print(f"Container target: {container_target}")
    print(f"Readable from LXC: {'yes' if readable else 'no'}")
    print(f"Writable from LXC: {'yes' if writable else 'no'}")
    if entry_count is not None:
        print(f"Visible entries: {entry_count}")
        if entry_count == 0:
            print("Warning: the media path is empty. If you expected a mounted library, check the host bind mount.")

    if not args.validate_only:
        host_mount = args.host_mount
        host_source = args.host_source or "<set-your-share-source>"
        if args.type == "nfs":
            fstab_line = f"{host_source} {host_mount} nfs defaults,_netdev 0 0"
        else:
            fstab_line = f"//server/share {host_mount} cifs credentials=/root/.smb-encodr,iocharset=utf8,_netdev 0 0"
        print("\nSuggested host-side /etc/fstab line:")
        print(f"  {fstab_line}")
        print("\nSuggested Proxmox LXC mount point:")
        print(f"  mp0: {host_mount},mp={container_target}")

    return 0 if readable else 1


def command_addhost(args: argparse.Namespace) -> int:
    from cli.docker import compose_env, compose_command
    project_root = Path(args.project_root).resolve()
    env_path = project_root / ".env"

    if not env_path.exists():
        print(f"Encodr environment file was not found at {env_path}.")
        return 1

    host = normalise_allowed_host(args.host)
    if host is None:
        print("Host names must not include a scheme, spaces, or commas.")
        return 1

    updated_hosts, changed = add_allowed_host_to_env(env_path, host)
    if not changed:
        print(f"{host} is already allowed.")
    else:
        print(f"Added {host} to ENCODR_UI_ALLOWED_HOSTS.")

    print("Recreating the Encodr stack to apply the updated UI host allowlist...")
    result = subprocess.run(
        compose_command(project_root, "up", "-d", "--force-recreate"),
        cwd=project_root,
        env=compose_env(project_root),
        check=False,
    )
    if result.returncode != 0:
        print("Failed to recreate the Encodr stack after updating the host allowlist.")
        return int(result.returncode)

    print(f"Allowed UI hosts: {', '.join(updated_hosts) if updated_hosts != ['*'] else '*'}")
    return 0


def build_update_checker(bundle: ConfigBundle) -> UpdateChecker:
    return UpdateChecker(
        current_version=read_version(REPO_ROOT),
        settings=UpdateCheckSettings(
            enabled=bundle.app.update.enabled,
            metadata_url=str(bundle.app.update.metadata_url) if bundle.app.update.metadata_url else None,
            channel=bundle.app.update.channel,
            timeout_seconds=bundle.app.update.check_timeout_seconds,
        ),
    )


def print_update_status(status) -> None:
    print(f"Current version: {status.current_version}")
    print(f"Check status: {status.status}")
    print(f"Channel: {status.channel}")
    if status.latest_version:
        print(f"Latest version: {status.latest_version}")
    if getattr(status, "release_name", None):
        print(f"Release: {status.release_name}")
    print(f"Update available: {'yes' if status.update_available else 'no'}")
    if status.checked_at:
        print(f"Checked at: {status.checked_at.isoformat()}")
    if status.error:
        print(f"Error: {status.error}")
    if getattr(status, "release_summary", None):
        print("Summary:")
        print(status.release_summary)
    if getattr(status, "breaking_changes_summary", None):
        print("Breaking changes:")
        print(status.breaking_changes_summary)
    if status.download_url:
        print(f"Download URL: {status.download_url}")


def apply_archive_update(*, project_root: Path, download_url: str) -> None:
    from cli.main import sync_release_tree
    with tempfile.TemporaryDirectory(prefix="encodr-update-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / "release.tar.gz"
        with urlopen(download_url, timeout=20) as response:  # noqa: S310
            archive_path.write_bytes(response.read())

        extract_dir = temp_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_dir)

        children = [child for child in extract_dir.iterdir() if not child.name.startswith(".")]
        source_root = children[0] if len(children) == 1 and children[0].is_dir() else extract_dir
        sync_release_tree(source_root=source_root, target_root=project_root)


def prompt_for_restart_after_update() -> None:
    from cli.main import detect_restart_environment
    environment = detect_restart_environment()
    restart_target = "this LXC container" if environment == "lxc" else "this system"
    print()
    print("Update complete.")
    print(
        f"A restart of {restart_target} may still be needed for storage mounts, GPU device passthrough, or remounted paths to be seen cleanly."
    )
    answer = input(f"Restart {restart_target} now? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Restart later if newly mounted storage or hardware devices are not visible yet.")
        return
    print(f"Restarting {restart_target}...")
    subprocess.run(["reboot"], check=True)


if __name__ == "__main__":
    raise SystemExit(main())
def read_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        if name.strip() == key:
            return raw_value.strip()
    return None


def normalise_allowed_host(value: str) -> str | None:
    host = value.strip()
    if not host or "://" in host or "," in host or any(char.isspace() for char in host):
        return None
    if host != "*" and not re.fullmatch(r"[A-Za-z0-9._-]+", host):
        return None
    return host


def add_allowed_host_to_env(env_path: Path, host: str) -> tuple[list[str], bool]:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    key = "ENCODR_UI_ALLOWED_HOSTS"
    current_hosts = ["localhost", "127.0.0.1"]
    existing_index: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        if name.strip() != key:
            continue
        existing_index = index
        current_hosts = parse_allowed_hosts(raw_value)
        break

    updated_hosts = current_hosts if "*" in current_hosts else unique_hosts([*current_hosts, host])
    updated_line = f"{key}={','.join(updated_hosts)}"

    if existing_index is None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(updated_line)
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return updated_hosts, True

    if lines[existing_index] == updated_line:
        return updated_hosts, False

    lines[existing_index] = updated_line
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return updated_hosts, True


def parse_allowed_hosts(raw_value: str) -> list[str]:
    stripped = raw_value.strip()
    if not stripped:
        return ["localhost", "127.0.0.1"]
    if stripped == "*":
        return ["*"]
    return unique_hosts(
        [host.strip() for host in stripped.split(",") if host.strip()],
    ) or ["localhost", "127.0.0.1"]


def unique_hosts(hosts: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for host in hosts:
        if host in seen:
            continue
        seen.add(host)
        ordered.append(host)
    return ordered


def local_ui_health_url(project_root: Path) -> str:
    from cli.utils import load_bundle
    env_port = read_env_value(project_root / ".env", "UI_PORT")
    if env_port:
        port = env_port
    else:
        public_url = str(load_bundle(project_root).app.ui.public_url)
        parsed = urlsplit(public_url)
        port = str(parsed.port) if parsed.port is not None else "5173"
    return f"http://127.0.0.1:{port}"


