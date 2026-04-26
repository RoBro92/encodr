#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Encodr"
REPO_OWNER="RoBro92"
REPO_NAME="encodr"
DEFAULT_INSTALL_ROOT="/opt/encodr"
DEFAULT_RELEASE_CHANNEL="latest"
STANDARD_MEDIA_ROOT="/media"
API_HEALTH_PATH="/api/health"

if [[ -t 1 ]]; then
  BLUE="$(printf '\033[1;34m')"
  GREEN="$(printf '\033[1;32m')"
  YELLOW="$(printf '\033[1;33m')"
  RED="$(printf '\033[1;31m')"
  BOLD="$(printf '\033[1m')"
  RESET="$(printf '\033[0m')"
else
  BLUE=""
  GREEN=""
  YELLOW=""
  RED=""
  BOLD=""
  RESET=""
fi

INSTALL_ROOT=""
SCRIPT_ROOT=""
REMOTE_BOOTSTRAP=0
INSTALL_REF_OVERRIDE=""
INSTALL_MODE_OVERRIDE=""
INSTALL_ACTION="install"
INSTALL_TMP_DIR=""

cleanup() {
  if [[ -n "${INSTALL_TMP_DIR:-}" && -d "${INSTALL_TMP_DIR}" ]]; then
    rm -rf "${INSTALL_TMP_DIR}"
  fi
}

trap cleanup EXIT

print_help() {
  cat <<EOF
Encodr installer

Usage:
  install.sh [--version REF] [--install-root PATH] [--repair|--fresh|--force-fresh|--abort-if-exists]

Options:
  --version REF       Install a specific tagged release instead of the default latest tagged release
  --install-root PATH Install into a custom directory instead of ${DEFAULT_INSTALL_ROOT}
  --repair            Repair an existing Encodr installation in place
  --fresh             Perform a fresh reinstall if an existing install is found
  --force-fresh       Confirm that a fresh reinstall should erase Encodr runtime state
  --abort-if-exists   Stop immediately if an existing install is found
  --help              Show this help message
EOF
}

section() {
  printf '\n%s== %s ==%s\n' "${BLUE}${BOLD}" "$1" "${RESET}"
}

info() {
  printf '%s•%s %s\n' "${BLUE}" "${RESET}" "$1"
}

success() {
  printf '%s✓%s %s\n' "${GREEN}" "${RESET}" "$1"
}

warn() {
  printf '%s!%s %s\n' "${YELLOW}" "${RESET}" "$1"
}

fail() {
  printf '%s✗%s %s\n' "${RED}" "${RESET}" "$1" >&2
  exit 1
}

run_with_progress() {
  local description="$1"
  shift

  local log_file=""
  log_file="$(mktemp "${TMPDIR:-/tmp}/encodr-install.XXXXXX.log")" || \
    fail "Unable to create a temporary log file for ${description}."

  info "${description}"
  if [[ -t 1 ]]; then
    local spinner='|/-\'
    local index=0
    "$@" >"${log_file}" 2>&1 &
    local command_pid=$!
    while kill -0 "${command_pid}" 2>/dev/null; do
      printf '\r%s[%c]%s %s' "${BLUE}" "${spinner:index++%${#spinner}:1}" "${RESET}" "${description}"
      sleep 0.1
    done

    local exit_code=0
    wait "${command_pid}" || exit_code=$?
    printf '\r\033[K'
    if [[ "${exit_code}" -ne 0 ]]; then
      warn "${description} failed. Showing recent output:"
      tail -n 40 "${log_file}" >&2 || true
      rm -f "${log_file}"
      return "${exit_code}"
    fi
  else
    if ! "$@" >"${log_file}" 2>&1; then
      warn "${description} failed. Showing recent output:"
      tail -n 40 "${log_file}" >&2 || true
      rm -f "${log_file}"
      return 1
    fi
  fi

  rm -f "${log_file}"
  success "${description} completed"
  return 0
}

run_compose_in_install_root() {
  (
    cd "${INSTALL_ROOT}" || exit 1
    local args=(-f docker-compose.yml)
    if [[ -f "${INSTALL_ROOT}/.runtime/compose.runtime.yml" ]]; then
      args+=(-f "${INSTALL_ROOT}/.runtime/compose.runtime.yml")
    fi
    docker compose "${args[@]}" "$@"
  )
}

run_managed_compose_in_install_root() {
  run_compose_in_install_root "$@"
}

generate_runtime_compose_override() {
  local generator="${INSTALL_ROOT}/infra/scripts/generate_runtime_compose.py"
  [[ -f "${generator}" ]] || return 0
  python3 "${generator}" --project-root "${INSTALL_ROOT}" || \
    fail "Unable to generate the Encodr runtime compose override."
}

parse_args() {
  local fresh_requested=0
  local fresh_confirmed=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version)
        [[ $# -ge 2 ]] || fail "--version requires a value."
        INSTALL_REF_OVERRIDE="$2"
        shift 2
        ;;
      --install-root)
        [[ $# -ge 2 ]] || fail "--install-root requires a value."
        INSTALL_ROOT="$2"
        shift 2
        ;;
      --repair)
        INSTALL_MODE_OVERRIDE="repair"
        shift
        ;;
      --fresh)
        fresh_requested=1
        INSTALL_MODE_OVERRIDE="fresh"
        shift
        ;;
      --force-fresh)
        fresh_confirmed=1
        shift
        ;;
      --abort-if-exists)
        INSTALL_MODE_OVERRIDE="abort"
        shift
        ;;
      --help|-h)
        print_help
        exit 0
        ;;
      *)
        fail "Unknown installer option: $1"
        ;;
    esac
  done

  if [[ "${fresh_confirmed}" -eq 1 && "${fresh_requested}" -eq 0 ]]; then
    fail "--force-fresh must be used together with --fresh."
  fi

  if [[ "${fresh_confirmed}" -eq 1 ]]; then
    INSTALL_MODE_OVERRIDE="fresh:confirmed"
  fi
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Run this installer as root inside the target Debian LXC."
  fi
}

resolve_script_root() {
  local source_dir
  local script_source="${BASH_SOURCE[0]-}"
  if [[ -n "${script_source}" ]]; then
    source_dir="$(cd "$(dirname "${script_source}")" 2>/dev/null && pwd || true)"
  else
    source_dir=""
  fi

  if [[ -n "${source_dir}" && -f "${source_dir}/docker-compose.yml" && -f "${source_dir}/.env.example" ]]; then
    SCRIPT_ROOT="${source_dir}"
    INSTALL_ROOT="${INSTALL_ROOT:-${source_dir}}"
    REMOTE_BOOTSTRAP=0
    return
  fi

  INSTALL_ROOT="${INSTALL_ROOT:-${ENCODR_INSTALL_ROOT:-${DEFAULT_INSTALL_ROOT}}}"
  SCRIPT_ROOT="${INSTALL_ROOT}"
  REMOTE_BOOTSTRAP=1
}

install_base_packages() {
  run_with_progress "Refreshing package metadata" apt-get update || fail "Unable to refresh package metadata."
  run_with_progress \
    "Installing base system packages" \
    apt-get install -y ca-certificates curl git jq gnupg lsb-release python3 python3-venv iproute2 tar || \
    fail "Unable to install the required base packages."
}

install_docker() {
  info "Installing Docker Engine and Compose plugin"
  install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi

  local codename
  codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
  cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${codename} stable
EOF

  run_with_progress "Refreshing Docker package metadata" apt-get update || \
    fail "Unable to refresh package metadata for Docker."
  run_with_progress \
    "Installing Docker Engine and Compose plugin" \
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin || \
    fail "Docker Engine or the Compose plugin could not be installed."
}

ensure_docker_daemon() {
  if ! docker info >/dev/null 2>&1; then
    fail "Docker is installed, but the Docker daemon is not available."
  fi
}

ensure_compose() {
  if ! docker compose version >/dev/null 2>&1; then
    fail "Docker Compose is not available."
  fi
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    install_docker
  fi

  if ! docker compose version >/dev/null 2>&1; then
    install_docker
  fi

  ensure_docker_daemon
  ensure_compose
}

prompt_input() {
  local prompt="$1"
  local response=""

  if [[ "${ENCODR_INSTALL_INTERACTIVE:-auto}" == "1" ]]; then
    printf '%s' "${prompt}" >&2
    IFS= read -r response || true
    printf '%s' "${response}"
    return 0
  fi

  if [[ -r /dev/tty && -w /dev/tty ]]; then
    printf '%s' "${prompt}" > /dev/tty
    IFS= read -r response < /dev/tty || true
    printf '%s' "${response}"
    return 0
  fi

  return 1
}

abort_install() {
  warn "$1"
  exit 0
}

existing_install_found() {
  [[ -d "${INSTALL_ROOT}" ]] || return 1
  [[ -f "${INSTALL_ROOT}/.env" ]] && return 0
  [[ -f "${INSTALL_ROOT}/docker-compose.yml" ]] && return 0
  [[ -d "${INSTALL_ROOT}/config" ]] && return 0
  [[ -d "${INSTALL_ROOT}/.runtime" ]] && return 0
  [[ -d "${INSTALL_ROOT}/postgres-data" ]] && return 0
  [[ -d "${INSTALL_ROOT}/redis-data" ]] && return 0
  return 1
}

resolve_install_mode() {
  if ! existing_install_found; then
    INSTALL_ACTION="install"
    return
  fi

  section "Existing installation detected"
  warn "An existing Encodr installation was found at ${INSTALL_ROOT}."

  case "${INSTALL_MODE_OVERRIDE:-}" in
    repair)
      INSTALL_ACTION="repair"
      info "Repair will preserve runtime data, generated config, secrets, and databases where possible."
      return
      ;;
    fresh:confirmed)
      INSTALL_ACTION="fresh"
      warn "Fresh install is destructive and will remove Encodr application files and runtime data."
      return
      ;;
    fresh)
      if [[ "${ENCODR_INSTALL_INTERACTIVE:-auto}" == "0" ]]; then
        fail "Fresh install is destructive. Re-run with --fresh --force-fresh."
      fi
      confirm_fresh_install
      return
      ;;
    abort)
      abort_install "Existing installation detected. No changes were made."
      ;;
    "")
      if [[ "${ENCODR_INSTALL_INTERACTIVE:-auto}" == "0" ]]; then
        fail "Existing installation detected. Re-run with one of: --repair, --fresh --force-fresh, --abort-if-exists."
      fi
      prompt_existing_install_action
      return
      ;;
    *)
      fail "Unsupported install mode: ${INSTALL_MODE_OVERRIDE}."
      ;;
  esac
}

show_fresh_install_plan() {
  warn "Fresh install will remove:"
  printf '  - %s/.env\n' "${INSTALL_ROOT}"
  printf '  - %s/config/\n' "${INSTALL_ROOT}"
  printf '  - %s/.runtime/\n' "${INSTALL_ROOT}"
  printf '  - %s/temp/\n' "${INSTALL_ROOT}"
  printf '  - %s/postgres-data/\n' "${INSTALL_ROOT}"
  printf '  - %s/redis-data/\n' "${INSTALL_ROOT}"
  printf '  - Encodr Docker containers, networks, local images, and Compose volumes\n'
  printf '  - %s application files\n' "${INSTALL_ROOT}"
}

detect_compose_project_name() {
  local env_file="${INSTALL_ROOT}/.env"
  [[ -f "${env_file}" ]] || {
    printf '%s\n' "${REPO_NAME}"
    return 0
  }

  python3 - "${env_file}" "${REPO_NAME}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
default_name = sys.argv[2]

for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != "PROJECT_NAME":
        continue
    value = value.strip().strip("\"'")
    print(value or default_name)
    raise SystemExit(0)

print(default_name)
PY
}

purge_remaining_compose_resources() {
  local project_name="$1"
  local container_ids=""
  local network_ids=""
  local volume_ids=""

  container_ids="$(docker ps -aq --filter "label=com.docker.compose.project=${project_name}" || true)"
  if [[ -n "${container_ids}" ]]; then
    info "Removing remaining Encodr containers"
    docker rm -f ${container_ids} >/dev/null 2>&1 || true
  fi

  network_ids="$(docker network ls -q --filter "label=com.docker.compose.project=${project_name}" || true)"
  if [[ -n "${network_ids}" ]]; then
    info "Removing remaining Encodr networks"
    docker network rm ${network_ids} >/dev/null 2>&1 || true
  fi

  volume_ids="$(docker volume ls -q --filter "label=com.docker.compose.project=${project_name}" || true)"
  if [[ -n "${volume_ids}" ]]; then
    info "Removing remaining Encodr volumes"
    docker volume rm -f ${volume_ids} >/dev/null 2>&1 || true
  fi
}

stop_existing_stack_for_fresh_install() {
  local project_name=""

  if [[ ! -f "${INSTALL_ROOT}/docker-compose.yml" ]]; then
    info "No existing Docker Compose project file was found to stop."
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker is not available, so the existing Encodr stack could not be stopped explicitly."
    return 0
  fi

  if ! docker compose version >/dev/null 2>&1; then
    warn "Docker Compose is not available, so the existing Encodr stack could not be stopped explicitly."
    return 0
  fi

  project_name="$(detect_compose_project_name)"

  section "Stopping existing Encodr stack"
  run_with_progress \
    "Stopping existing Docker services" \
    run_compose_in_install_root down --remove-orphans --volumes --rmi local || \
    fail "Unable to stop the existing Encodr Docker stack before the fresh reinstall."

  section "Purging existing Encodr Docker resources"
  run_with_progress \
    "Removing leftover Encodr Docker resources" \
    purge_remaining_compose_resources "${project_name}" || \
    fail "Unable to remove leftover Encodr Docker resources before the fresh reinstall."
}

confirm_fresh_install() {
  show_fresh_install_plan
  local confirmation=""
  confirmation="$(prompt_input "Type DELETE to confirm a destructive fresh install: ")" || \
    fail "Interactive confirmation is unavailable. Re-run with --fresh --force-fresh."
  if [[ "${confirmation}" != "DELETE" ]]; then
    abort_install "Fresh install cancelled. No changes were made."
  fi
  INSTALL_ACTION="fresh"
}

prompt_existing_install_action() {
  local selection=""
  selection="$(
    prompt_input $'Choose what to do:\n  [1] Repair existing installation\n  [2] Fresh install (destructive)\n  [3] Abort\nSelection [3]: '
  )" || fail "Interactive selection is unavailable. Re-run with --repair, --fresh --force-fresh, or --abort-if-exists."
  case "${selection}" in
    1)
      INSTALL_ACTION="repair"
      info "Repair will preserve runtime data, generated config, secrets, and databases where possible."
      ;;
    2)
      confirm_fresh_install
      ;;
    ""|3)
      abort_install "Installer aborted. No changes were made."
      ;;
    *)
      abort_install "Installer aborted. No changes were made."
      ;;
  esac
}

perform_fresh_install_reset() {
  section "Removing existing installation"
  if [[ "${REMOTE_BOOTSTRAP}" -ne 1 ]]; then
    fail "Fresh install is not supported from a live checkout. Remove the checkout manually and run the installer again."
  fi

  show_fresh_install_plan
  stop_existing_stack_for_fresh_install
  rm -rf "${INSTALL_ROOT}" || fail "Unable to remove the existing Encodr installation."
  success "Existing installation removed"
}

download_release_tree() {
  local ref="${INSTALL_REF_OVERRIDE:-${ENCODR_INSTALL_REF:-}}"
  local selected_url=""

  if [[ -z "${ref}" ]]; then
    info "Resolving the latest tagged release"
    ref="$(resolve_latest_release_tag)"
  fi

  section "Resolving release source"
  info "Installing ${ref} into ${INSTALL_ROOT}"
  INSTALL_TMP_DIR="$(mktemp -d)" || fail "Unable to create a temporary installer directory."

  section "Downloading release files"
  mkdir -p "${INSTALL_ROOT}" || fail "Unable to create ${INSTALL_ROOT}."

  selected_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${ref}.tar.gz"
  curl -fsSL "${selected_url}" -o "${INSTALL_TMP_DIR}/encodr.tar.gz" || \
    fail "Unable to download the Encodr tagged release ${ref}."

  tar -xzf "${INSTALL_TMP_DIR}/encodr.tar.gz" -C "${INSTALL_TMP_DIR}" || fail "Downloaded archive could not be unpacked."
  local extracted_dir
  extracted_dir="$(find "${INSTALL_TMP_DIR}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "${extracted_dir}" ]] || fail "Downloaded archive could not be unpacked."

  section "Preparing install directory"
  mkdir -p "${INSTALL_ROOT}"
  # Preserve runtime state and generated local config during repair/reinstall runs.
  find "${INSTALL_ROOT}" -mindepth 1 -maxdepth 1 \
    ! -name '.env' \
    ! -name '.runtime' \
    ! -name 'config' \
    ! -name 'temp' \
    ! -name 'postgres-data' \
    ! -name 'redis-data' \
    -exec rm -rf {} +
  cp -R "${extracted_dir}/." "${INSTALL_ROOT}/"
  success "Release files are in place"
}

prepare_install_root_for_sync() {
  section "Preparing install directory"
  mkdir -p "${INSTALL_ROOT}"
  find "${INSTALL_ROOT}" -mindepth 1 -maxdepth 1 \
    ! -name '.env' \
    ! -name '.runtime' \
    ! -name 'config' \
    ! -name 'temp' \
    ! -name 'postgres-data' \
    ! -name 'redis-data' \
    -exec rm -rf {} +
}

sync_local_checkout_tree() {
  local source_root
  local target_root
  source_root="$(cd "${SCRIPT_ROOT}" && pwd -P)"
  mkdir -p "${INSTALL_ROOT}"
  target_root="$(cd "${INSTALL_ROOT}" && pwd -P)"

  if [[ "${source_root}" == "${target_root}" ]]; then
    success "Installer will use the local repository files"
    return 0
  fi

  prepare_install_root_for_sync

  if [[ -d "${SCRIPT_ROOT}/.git" ]] && command -v git >/dev/null 2>&1; then
    local tracked_files_list=""
    tracked_files_list="$(mktemp "${TMPDIR:-/tmp}/encodr-install-files.XXXXXX")" || \
      fail "Unable to prepare the local checkout file list."
    (
      cd "${SCRIPT_ROOT}" &&
      git ls-files -z > "${tracked_files_list}"
    ) || {
      rm -f "${tracked_files_list}"
      fail "Unable to enumerate tracked files from the local checkout."
    }
    python3 - "${SCRIPT_ROOT}" "${INSTALL_ROOT}" "${tracked_files_list}" <<'PY' || {
from pathlib import Path
import shutil
import sys

source_root = Path(sys.argv[1])
target_root = Path(sys.argv[2])
tracked_list = Path(sys.argv[3])

for raw_path in tracked_list.read_bytes().split(b"\0"):
    if not raw_path:
        continue
    relative = Path(raw_path.decode("utf-8"))
    source_path = source_root / relative
    if not source_path.exists():
        continue
    target_path = target_root / relative
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
PY
      rm -f "${tracked_files_list}"
      fail "Unable to copy the local checkout into ${INSTALL_ROOT}."
    }
    rm -f "${tracked_files_list}"
  else
    tar \
      --exclude-vcs \
      --exclude='.env' \
      --exclude='.runtime' \
      --exclude='config/app.yaml' \
      --exclude='config/policy.yaml' \
      --exclude='config/workers.yaml' \
      --exclude='dev-local' \
      -C "${SCRIPT_ROOT}" -cf - . | tar -C "${INSTALL_ROOT}" -xf - || \
      fail "Unable to copy the local checkout into ${INSTALL_ROOT}."
  fi

  success "Local checkout files are in place"
}

resolve_latest_release_tag() {
  local release_metadata_url="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest"
  local latest_tag=""

  latest_tag="$(
    curl -fsSL "${release_metadata_url}" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
tag_name = str(payload.get("tag_name") or "").strip()
if not tag_name:
    raise SystemExit(1)
print(tag_name)
'
  )" || fail "Unable to resolve the latest Encodr tagged release."

  printf '%s\n' "${latest_tag}"
}

ensure_release_tree() {
  if [[ "${REMOTE_BOOTSTRAP}" -eq 1 ]]; then
    resolve_install_mode
    if [[ "${INSTALL_ACTION}" == "fresh" ]]; then
      perform_fresh_install_reset
    fi
    download_release_tree
  else
    section "Using local checkout"
    info "Installing from ${SCRIPT_ROOT} into ${INSTALL_ROOT}"
    sync_local_checkout_tree
  fi
}

ensure_secret() {
  local variable_name="$1"
  local placeholder="change-me-before-production"
  if grep -q "^${variable_name}=${placeholder}$" "${INSTALL_ROOT}/.env"; then
    local generated
    generated="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
    python3 - "${INSTALL_ROOT}/.env" "${variable_name}" "${generated}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
name = sys.argv[2]
value = sys.argv[3]
lines = env_path.read_text(encoding="utf-8").splitlines()
updated = [f"{name}={value}" if line.startswith(f"{name}=") else line for line in lines]
env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
    success "Generated ${variable_name}"
  else
    info "${variable_name} already set"
  fi
}

sync_database_dsn_with_env() {
  local env_file="${INSTALL_ROOT}/.env"
  local app_config_file="${INSTALL_ROOT}/config/app.yaml"
  [[ -f "${env_file}" && -f "${app_config_file}" ]] || return 0

  python3 - "${env_file}" "${app_config_file}" <<'PY'
from pathlib import Path
from urllib.parse import quote
import sys

env_path = Path(sys.argv[1])
app_config_path = Path(sys.argv[2])

env: dict[str, str] = {}
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip().strip("\"'")

database_name = env.get("POSTGRES_DB", "encodr")
database_user = env.get("POSTGRES_USER", "encodr")
database_password = env.get("POSTGRES_PASSWORD", "")
if not database_password:
    raise SystemExit(0)

next_dsn = (
    "postgresql+psycopg://"
    f"{quote(database_user, safe='')}:{quote(database_password, safe='')}@postgres:5432/"
    f"{quote(database_name, safe='')}"
)

lines = app_config_path.read_text(encoding="utf-8").splitlines()
updated: list[str] = []
changed = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("dsn:"):
        current = stripped.split(":", 1)[1].strip().strip("\"'")
        if "@postgres:" in current and (
            "change-me-before-production" in current or "encodr-dev-password" in current
        ):
            indent = line[: len(line) - len(line.lstrip())]
            updated.append(f"{indent}dsn: {next_dsn}")
            changed = True
            continue
    updated.append(line)

if changed:
    app_config_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
}

prepare_management_cli_runtime() {
  section "Preparing management CLI"
  local cli_venv="${INSTALL_ROOT}/.runtime/cli-venv"
  local cli_python="${cli_venv}/bin/python"
  local cli_pip="${cli_venv}/bin/pip"

  if [[ ! -x "${cli_python}" ]]; then
    run_with_progress "Creating the Encodr management virtual environment" \
      python3 -m venv "${cli_venv}" || fail "Unable to create the Encodr management virtual environment."
  else
    info "Encodr management virtual environment already exists"
  fi

  run_with_progress \
    "Installing Encodr management command dependencies" \
    "${cli_pip}" install --no-cache-dir \
      "psycopg[binary]>=3.1,<4.0" \
      -e "${INSTALL_ROOT}/packages/core" \
      -e "${INSTALL_ROOT}/packages/shared" \
      -e "${INSTALL_ROOT}/packages/db" \
      -e "${INSTALL_ROOT}/apps/api" || \
    fail "Unable to install Encodr management command dependencies."
}

install_startup_service() {
  local unit_path="/etc/systemd/system/encodr.service"
  local compose_files="-f ${INSTALL_ROOT}/docker-compose.yml"

  if [[ -f "${INSTALL_ROOT}/.runtime/compose.runtime.yml" ]]; then
    compose_files="${compose_files} -f ${INSTALL_ROOT}/.runtime/compose.runtime.yml"
  fi

  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl is not available, so automatic stack restart on boot could not be configured."
    return 0
  fi

  section "Configuring startup"
  cat >"${unit_path}" <<EOF
[Unit]
Description=Encodr Docker Compose stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${INSTALL_ROOT}
ExecStart=/usr/bin/docker compose ${compose_files} up -d
ExecStop=/usr/bin/docker compose ${compose_files} down
RemainAfterExit=yes
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

  run_with_progress "Enabling the Encodr startup service" systemctl daemon-reload || \
    fail "Unable to reload systemd after installing the Encodr startup service."
  run_with_progress "Enabling Encodr to start automatically on boot" systemctl enable encodr.service || \
    fail "Unable to enable the Encodr startup service."
}

normalise_host_config_paths_in_env() {
  local env_file="${INSTALL_ROOT}/.env"
  [[ -f "${env_file}" ]] || return 0

  local app_config_path="${INSTALL_ROOT}/config/app.yaml"
  local policy_config_path="${INSTALL_ROOT}/config/policy.yaml"
  local workers_config_path="${INSTALL_ROOT}/config/workers.yaml"

  python3 - "${env_file}" "${app_config_path}" "${policy_config_path}" "${workers_config_path}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
desired = {
    "ENCODR_APP_CONFIG_FILE": sys.argv[2],
    "ENCODR_POLICY_CONFIG_FILE": sys.argv[3],
    "ENCODR_WORKERS_CONFIG_FILE": sys.argv[4],
}

lines = env_path.read_text(encoding="utf-8").splitlines()
seen = set()
updated = []

for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        updated.append(line)
        continue

    key, value = line.split("=", 1)
    key = key.strip()
    if key in desired:
        updated.append(f"{key}={desired[key]}")
        seen.add(key)
    else:
        updated.append(line)

for key, value in desired.items():
    if key not in seen:
        updated.append(f"{key}={value}")

env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
}

load_env() {
  local env_file="${INSTALL_ROOT}/.env"
  [[ -f "${env_file}" ]] || fail "Expected environment file at ${env_file}."

  local raw_line=""
  local line=""
  local key=""
  local value=""
  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    line="${raw_line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"

    [[ -z "${line}" ]] && continue
    [[ "${line:0:1}" == "#" ]] && continue

    if [[ "${line}" == export\ * ]]; then
      line="${line#export }"
    fi

    [[ "${line}" == *=* ]] || fail "Invalid dotenv line in ${env_file}: ${raw_line}"

    key="${line%%=*}"
    value="${line#*=}"

    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"

    [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "Invalid dotenv key in ${env_file}: ${key}"

    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    export "${key}=${value}"
  done < "${env_file}"
}

detect_network_ip_addresses() {
  python3 - <<'PY'
import ipaddress
import re
import subprocess

try:
    output = subprocess.check_output(
        ["ip", "-o", "-4", "addr", "show", "up", "scope", "global"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
except Exception:
    raise SystemExit(0)

ignored_interface_patterns = (
    re.compile(r"^docker\d+$"),
    re.compile(r"^br-.+"),
    re.compile(r"^veth.+"),
    re.compile(r"^lo$"),
)

addresses: list[str] = []
seen: set[str] = set()

for raw_line in output.splitlines():
    parts = raw_line.split()
    if len(parts) < 4:
        continue
    interface_name = parts[1]
    if any(pattern.match(interface_name) for pattern in ignored_interface_patterns):
        continue
    cidr = parts[3]
    address_text = cidr.split("/", 1)[0]
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError:
        continue
    if address.is_loopback or address.is_link_local:
        continue
    if address_text in seen:
        continue
    seen.add(address_text)
    addresses.append(address_text)

for address in addresses:
    print(address)
PY
}

ensure_ui_allowed_hosts_for_network_ips() {
  local env_file="${INSTALL_ROOT}/.env"
  [[ -f "${env_file}" ]] || return 0

  local network_addresses=()
  local address=""
  while IFS= read -r address; do
    [[ -n "${address}" ]] || continue
    network_addresses+=("${address}")
  done < <(detect_network_ip_addresses)
  [[ "${#network_addresses[@]}" -gt 0 ]] || return 0

  python3 - "${env_file}" "${network_addresses[@]}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
additional_hosts = [value.strip() for value in sys.argv[2:] if value.strip()]
key = "ENCODR_UI_ALLOWED_HOSTS"

lines = env_path.read_text(encoding="utf-8").splitlines()
existing_index = None
existing_hosts: list[str] = []

for index, raw_line in enumerate(lines):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        continue
    current_key, value = line.split("=", 1)
    if current_key.strip() != key:
        continue
    existing_index = index
    existing_hosts = [item.strip() for item in value.split(",") if item.strip()]
    break

merged_hosts: list[str] = []
seen: set[str] = set()
for host in [*existing_hosts, *additional_hosts]:
    if host in seen:
        continue
    seen.add(host)
    merged_hosts.append(host)

updated_line = f"{key}={','.join(merged_hosts)}"
if existing_index is None:
    lines.append(updated_line)
else:
    lines[existing_index] = updated_line

env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

wait_for_health() {
  local api_port="${API_PORT:-8000}"
  local url="http://127.0.0.1:${api_port}${API_HEALTH_PATH}"

  info "Waiting for API health at ${url}"
  for _ in $(seq 1 45); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      success "API health check passed"
      return 0
    fi
    sleep 2
  done

  fail "API health check did not succeed at ${url}"
}

show_urls() {
  local api_port="${API_PORT:-8000}"
  local ui_port="${UI_PORT:-5173}"
  local network_addresses=()
  local address=""
  while IFS= read -r address; do
    [[ -n "${address}" ]] || continue
    network_addresses+=("${address}")
  done < <(detect_network_ip_addresses)

  section "Encodr is ready"
  printf '%s%s%s\n' "${BOLD}" "Web UI" "${RESET}: http://127.0.0.1:${ui_port}"
  printf '%s%s%s\n' "${BOLD}" "API health" "${RESET}: http://127.0.0.1:${api_port}${API_HEALTH_PATH}"

  if [[ "${#network_addresses[@]}" -gt 0 ]]; then
    info "Detected network IP address(es): ${network_addresses[*]}"
    for address in "${network_addresses[@]}"; do
      info "UI on the network: http://${address}:${ui_port}"
    done
  fi

  printf '\n%sNext steps%s\n' "${BOLD}" "${RESET}"
  printf '1. Open Encodr in your browser.\n'
  printf '2. Create your first admin user if prompted.\n'
  printf '3. Confirm your media library at %s and scratch storage at /temp.\n' "${STANDARD_MEDIA_ROOT}"
  printf '4. Run %s or %s.\n' "encodr doctor" "encodr status"
  printf '5. Run %s after your mount is ready.\n' "encodr mount-setup --validate-only"
}

main() {
  parse_args "$@"
  require_root
  resolve_script_root

  section "Checking environment"
  install_base_packages
  ensure_docker

  ensure_release_tree
  cd "${INSTALL_ROOT}"

  section "Bootstrapping Encodr"
  ./infra/scripts/bootstrap.sh >/dev/null
  normalise_host_config_paths_in_env
  ensure_secret "POSTGRES_PASSWORD"
  sync_database_dsn_with_env
  ensure_secret "ENCODR_AUTH_SECRET"
  ensure_secret "ENCODR_WORKER_REGISTRATION_SECRET"
  ensure_ui_allowed_hosts_for_network_ips
  generate_runtime_compose_override
  prepare_management_cli_runtime

  mkdir -p /usr/local/bin
  ln -sf "${INSTALL_ROOT}/encodr" /usr/local/bin/encodr
  success "Installed the encodr management command"
  install_startup_service

  load_env

  section "Starting the stack"
  run_with_progress "Launching Docker services" run_managed_compose_in_install_root up -d --build || \
    fail "Docker Compose could not start the Encodr stack."

  section "Waiting for health"
  wait_for_health
  section "Verifying installation"
  ./encodr doctor >/dev/null || fail "Encodr started, but the final doctor checks did not pass."
  success "Doctor checks passed"

  section "Final summary"
  show_urls
}

if [[ "${ENCODR_INSTALL_LIB_ONLY:-0}" != "1" ]]; then
  main "$@"
fi
