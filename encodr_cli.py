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

    help_parser = subparsers.add_parser("help", help="Show command help.")
    help_parser.set_defaults(func=lambda args: parser.print_help() or 0)

    doctor_parser = subparsers.add_parser("doctor", help="Run local health and configuration checks.")
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

    health_parser = subparsers.add_parser("health", help="Run a quick local stack health check.")
    health_parser.set_defaults(func=command_health)

    rebuild_parser = subparsers.add_parser("rebuild", help="Rebuild and recreate the local Docker Compose stack.")
    rebuild_parser.set_defaults(func=command_rebuild)

    dev_ui_parser = subparsers.add_parser("dev-ui", help="Run the UI in local development mode against the local API.")
    dev_ui_parser.set_defaults(func=command_dev_ui)

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


def command_version(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.project_root)
    print(f"Encodr {read_version(Path(args.project_root))}")
    print(f"Environment: {bundle.app.environment.value}")
    print(f"API base path: {bundle.app.api.base_path}")
    print(f"UI URL: {bundle.app.ui.public_url}")
    return 0


def command_start(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    ensure_local_storage_mounts(project_root)
    print("Starting Encodr locally with Docker Compose...")
    return run_compose(args, ["up", "-d", "--build"])


def command_stop(args: argparse.Namespace) -> int:
    print("Stopping the local Encodr stack...")
    return run_compose(args, ["stop"])


def command_restart(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    ensure_local_storage_mounts(project_root)
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


def command_health(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
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
    project_root = Path(args.project_root).resolve()
    bootstrap_repo(project_root)
    ensure_local_storage_mounts(project_root)
    print("Rebuilding and recreating the local Encodr stack...")
    return run_compose(args, ["up", "-d", "--build", "--force-recreate"])


def command_dev_ui(args: argparse.Namespace) -> int:
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


def command_doctor(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    bundle = load_bundle(project_root)
    api_health = check_api_health(bundle)
    doctor_mode = "host-direct"

    dockerised_payload = maybe_collect_dockerised_doctor_payload(project_root)
    if dockerised_payload is not None:
        runtime = dockerised_payload["runtime"]
        storage = dockerised_payload["storage"]
        doctor_mode = "docker-compose/api-container"
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
    subprocess.run(
        compose_command(project_root, "up", "-d", "--build"),
        cwd=project_root,
        env=compose_env(project_root),
        check=True,
    )
    doctor_result = command_doctor(args)
    prompt_for_restart_after_update()
    return doctor_result


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


def compose_env(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    media_root, temp_root = ensure_local_storage_mounts(project_root)
    env.setdefault("ENCODR_MEDIA_HOST_PATH", str(media_root))
    env.setdefault("ENCODR_TEMP_HOST_PATH", str(temp_root))
    return env


def local_ui_health_url(project_root: Path) -> str:
    env_port = read_env_value(project_root / ".env", "UI_PORT")
    if env_port:
        port = env_port
    else:
        public_url = str(load_bundle(project_root).app.ui.public_url)
        parsed = urlsplit(public_url)
        port = str(parsed.port) if parsed.port is not None else "5173"
    return f"http://127.0.0.1:{port}"


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


def run_compose(args: argparse.Namespace, compose_args: list[str]) -> int:
    project_root = Path(args.project_root).resolve()
    result = subprocess.run(
        compose_command(project_root, *compose_args),
        cwd=project_root,
        env=compose_env(project_root),
        check=False,
    )
    return int(result.returncode)


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


def create_session_factory(bundle: ConfigBundle) -> sessionmaker:
    engine = create_engine(bundle.app.database.dsn, future=True)
    return sessionmaker(engine, future=True, expire_on_commit=False)


def maybe_collect_dockerised_doctor_payload(project_root: Path) -> dict[str, object] | None:
    if not should_use_dockerised_doctor(project_root):
        return None

    diagnostics = docker_compose_exec_api_python(
        project_root,
        """
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
""".strip(),
    )

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


def should_use_dockerised_doctor(project_root: Path) -> bool:
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
    if compose_version.returncode != 0:
        return False

    api_exec = subprocess.run(
        compose_command(project_root, "exec", "-T", "api", "true"),
        cwd=project_root,
        env=compose_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return api_exec.returncode == 0


def docker_compose_exec_api_python(project_root: Path, script: str) -> str | None:
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


def check_api_health(bundle: ConfigBundle) -> dict[str, str]:
    url = f"http://127.0.0.1:{bundle.app.api.port}{bundle.app.api.base_path}/health"
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return {"status": "healthy", "summary": f"API responded with {payload.get('status', 'ok')}."}
    except (URLError, OSError, json.JSONDecodeError) as error:
        return {"status": "failed", "summary": str(error)}


def compose_command(project_root: Path, *compose_args: str) -> list[str]:
    command = ["docker", "compose"]
    local_override = project_root / "infra" / "compose" / "local.override.yml"
    if (project_root / ".git").exists() and local_override.exists():
        command.extend(["-f", "docker-compose.yml", "-f", str(local_override)])
    command.extend(compose_args)
    return command


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


def prompt_for_restart_after_update() -> None:
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
