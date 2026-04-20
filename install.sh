#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Encodr"
REPO_OWNER="RoBro92"
REPO_NAME="encodr"
DEFAULT_INSTALL_ROOT="/opt/encodr"
DEFAULT_INSTALL_REF="main"
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
  --version REF       Install a specific git tag or branch instead of the default ${DEFAULT_INSTALL_REF}
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
    apt-get install -y ca-certificates curl git jq gnupg lsb-release python3 iproute2 tar || \
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
  printf '  - %s/scratch/\n' "${INSTALL_ROOT}"
  printf '  - %s/postgres-data/\n' "${INSTALL_ROOT}"
  printf '  - %s/redis-data/\n' "${INSTALL_ROOT}"
  printf '  - %s application files\n' "${INSTALL_ROOT}"
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
  rm -rf "${INSTALL_ROOT}" || fail "Unable to remove the existing Encodr installation."
  success "Existing installation removed"
}

download_release_tree() {
  local ref="${INSTALL_REF_OVERRIDE:-${ENCODR_INSTALL_REF:-${DEFAULT_INSTALL_REF}}}"
  local tag_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${ref}.tar.gz"
  local branch_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${ref}.tar.gz"
  local selected_url="${tag_url}"

  section "Resolving release source"
  info "Installing ${ref} into ${INSTALL_ROOT}"
  INSTALL_TMP_DIR="$(mktemp -d)" || fail "Unable to create a temporary installer directory."

  section "Downloading release files"
  mkdir -p "${INSTALL_ROOT}" || fail "Unable to create ${INSTALL_ROOT}."

  if ! curl -fsSL "${selected_url}" -o "${INSTALL_TMP_DIR}/encodr.tar.gz"; then
    selected_url="${branch_url}"
    info "Tag archive not found, falling back to branch archive ${ref}"
    curl -fsSL "${selected_url}" -o "${INSTALL_TMP_DIR}/encodr.tar.gz" || \
      fail "Unable to download Encodr from ${ref}."
  fi

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
    ! -name 'scratch' \
    ! -name 'postgres-data' \
    ! -name 'redis-data' \
    -exec rm -rf {} +
  cp -R "${extracted_dir}/." "${INSTALL_ROOT}/"
  success "Release files are in place"
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
    info "Installing from ${INSTALL_ROOT}"
    success "Installer will use the local repository files"
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
  local addresses
  addresses="$(hostname -I 2>/dev/null || true)"

  section "Encodr is ready"
  printf '%s%s%s\n' "${BOLD}" "Web UI" "${RESET}: http://127.0.0.1:${ui_port}"
  printf '%s%s%s\n' "${BOLD}" "API health" "${RESET}: http://127.0.0.1:${api_port}${API_HEALTH_PATH}"

  if [[ -n "${addresses// }" ]]; then
    info "Detected container IP address(es): ${addresses}"
    for address in ${addresses}; do
      info "UI on the network: http://${address}:${ui_port}"
    done
  fi

  printf '\n%sNext steps%s\n' "${BOLD}" "${RESET}"
  printf '1. Open Encodr in your browser.\n'
  printf '2. Create your first admin user if prompted.\n'
  printf '3. Mount your media library at %s.\n' "${STANDARD_MEDIA_ROOT}"
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
  ensure_secret "ENCODR_AUTH_SECRET"
  ensure_secret "ENCODR_WORKER_REGISTRATION_SECRET"

  mkdir -p /usr/local/bin
  ln -sf "${INSTALL_ROOT}/encodr" /usr/local/bin/encodr
  success "Installed the encodr management command"

  load_env

  section "Starting the stack"
  run_with_progress "Launching Docker services" docker compose up -d --build || \
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
