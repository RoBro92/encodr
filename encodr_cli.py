from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parent
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
from encodr_shared import UpdateCheckSettings, UpdateChecker, read_version


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="encodr", description="Encodr operator management CLI.")
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="Path to the Encodr installation root.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser("version", help="Show the installed Encodr version.")
    version_parser.set_defaults(func=command_version)

    doctor_parser = subparsers.add_parser("doctor", help="Run local health and configuration checks.")
    doctor_parser.set_defaults(func=command_doctor)

    status_parser = subparsers.add_parser("status", help="Alias for doctor.")
    status_parser.set_defaults(func=command_doctor)

    update_parser = subparsers.add_parser("update", help="Check for updates and optionally apply one.")
    update_parser.add_argument("--apply", action="store_true", help="Download and apply the available update.")
    update_parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt when applying.")
    update_parser.set_defaults(func=command_update)

    update_check_parser = subparsers.add_parser("update-check", help="Check for updates without applying one.")
    update_check_parser.set_defaults(func=command_update_check)

    reset_admin_parser = subparsers.add_parser("reset-admin", help="Create or reset an admin user password.")
    reset_admin_parser.add_argument("--username", default="admin", help="Admin username to create or reset.")
    reset_admin_parser.add_argument("--password", help="New password. If omitted, prompt securely.")
    reset_admin_parser.set_defaults(func=command_reset_admin)

    mount_parser = subparsers.add_parser("mount-setup", help="Generate and validate storage mount guidance.")
    mount_parser.add_argument("--type", choices=["nfs", "smb"], default="nfs", help="Share type for guidance output.")
    mount_parser.add_argument("--host-source", help="Host-side network share source, for example 10.0.0.10:/share.")
    mount_parser.add_argument("--host-mount", default="/mnt/pve/encodr-media", help="Recommended host-side mount path.")
    mount_parser.add_argument("--container-target", help="Container-visible mount path. Defaults to the first configured media mount.")
    mount_parser.add_argument("--create-dirs", action="store_true", help="Create the target directory inside the LXC if missing.")
    mount_parser.add_argument("--validate-only", action="store_true", help="Only validate current mounted paths.")
    mount_parser.set_defaults(func=command_mount_setup)

    return parser


def command_version(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.project_root)
    print(f"Encodr {read_version(Path(args.project_root))}")
    print(f"Environment: {bundle.app.environment.value}")
    print(f"API base path: {bundle.app.api.base_path}")
    print(f"UI URL: {bundle.app.ui.public_url}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.project_root)
    session_factory = create_session_factory(bundle)
    system_service_class = get_system_service_class()
    system = system_service_class(
        config_bundle=bundle,
        session_factory=session_factory,
        app_version=read_version(Path(args.project_root)),
    )
    runtime = system.runtime_status()
    storage = system.storage_status()
    api_health = check_api_health(bundle)

    print(f"Version: {runtime['version']}")
    print(f"Runtime: {runtime['status']} - {runtime['summary']}")
    print(f"API health: {api_health['status']} - {api_health['summary']}")
    print(f"Database reachable: {'yes' if runtime['db_reachable'] else 'no'}")
    print(f"Schema reachable: {'yes' if runtime['schema_reachable'] else 'no'}")
    print(f"First-user setup required: {'yes' if runtime['first_user_setup_required'] else 'no'}")
    print(f"Storage: {storage['status']} - {storage['summary']}")
    for item in [storage["scratch"], storage["data_dir"], *storage["media_mounts"]]:
        print(f"  - {item['role']}: {item['status']} ({item['path']})")

    failed = any(
        [
            runtime["status"] == "failed",
            storage["status"] == "failed",
            api_health["status"] == "failed",
        ]
    )
    return 1 if failed else 0


def command_update_check(args: argparse.Namespace) -> int:
    checker = build_update_checker(load_bundle(args.project_root))
    status = checker.check_now()
    print_update_status(status)
    return 0 if status.status != "error" else 1


def command_update(args: argparse.Namespace) -> int:
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
    subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=project_root, check=True)
    return command_doctor(args)


def command_reset_admin(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.project_root)
    session_factory = create_session_factory(bundle)
    password = args.password or getpass.getpass("New admin password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return 1

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


def command_mount_setup(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.project_root)
    container_target = args.container_target or (
        bundle.workers.local.media_mounts[0].as_posix()
        if bundle.workers.local.media_mounts
        else "/mnt/media"
    )
    target_path = Path(container_target)

    if args.create_dirs:
        target_path.mkdir(parents=True, exist_ok=True)

    readable = target_path.exists() and os.access(target_path, os.R_OK)
    writable = target_path.exists() and os.access(target_path, os.W_OK)

    print("Recommended model: mount the share on the Proxmox host, bind-mount it into the LXC, then bind it into Docker inside the LXC.")
    print(f"Container target: {container_target}")
    print(f"Readable from LXC: {'yes' if readable else 'no'}")
    print(f"Writable from LXC: {'yes' if writable else 'no'}")

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


def load_bundle(project_root: str | Path) -> ConfigBundle:
    return load_config_bundle(project_root=Path(project_root).resolve())


def create_session_factory(bundle: ConfigBundle) -> sessionmaker:
    engine = create_engine(bundle.app.database.dsn, future=True)
    return sessionmaker(engine, future=True, expire_on_commit=False)


def check_api_health(bundle: ConfigBundle) -> dict[str, str]:
    url = f"http://127.0.0.1:{bundle.app.api.port}{bundle.app.api.base_path}/health"
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return {"status": "healthy", "summary": f"API responded with {payload.get('status', 'ok')}."}
    except (URLError, OSError, json.JSONDecodeError) as error:
        return {"status": "failed", "summary": str(error)}


def get_password_hash_service_class():
    module = importlib.import_module("app.core.security")
    return module.PasswordHashService


def get_system_service_class():
    module = importlib.import_module("app.services.system")
    return module.SystemService


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
    print(f"Update available: {'yes' if status.update_available else 'no'}")
    if status.checked_at:
        print(f"Checked at: {status.checked_at.isoformat()}")
    if status.error:
        print(f"Error: {status.error}")
    if status.download_url:
        print(f"Download URL: {status.download_url}")


def apply_archive_update(*, project_root: Path, download_url: str) -> None:
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


def sync_release_tree(*, source_root: Path, target_root: Path) -> None:
    excluded_names = {".git", ".env", ".runtime", "postgres-data", "redis-data", "scratch", "__pycache__", "node_modules"}
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


if __name__ == "__main__":
    raise SystemExit(main())
