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

print_help() {
  cat <<EOF
Encodr installer

Usage:
  install.sh [--version REF] [--install-root PATH]

Options:
  --version REF       Install a specific git tag or branch instead of the default ${DEFAULT_INSTALL_REF}
  --install-root PATH Install into a custom directory instead of ${DEFAULT_INSTALL_ROOT}
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

parse_args() {
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
      --help|-h)
        print_help
        exit 0
        ;;
      *)
        fail "Unknown installer option: $1"
        ;;
    esac
  done
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Run this installer as root inside the target Debian LXC."
  fi
}

resolve_script_root() {
  local source_dir
  source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"

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
  info "Installing base system packages"
  apt-get update >/dev/null || fail "Unable to refresh package metadata."
  apt-get install -y ca-certificates curl git jq gnupg lsb-release python3 iproute2 tar >/dev/null || \
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

  apt-get update >/dev/null || fail "Unable to refresh package metadata for Docker."
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null || \
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

download_release_tree() {
  local ref="${INSTALL_REF_OVERRIDE:-${ENCODR_INSTALL_REF:-${DEFAULT_INSTALL_REF}}}"
  local archive_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${ref}.tar.gz"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir}"' RETURN

  section "Downloading ${APP_NAME}"
  info "Installing ${ref} into ${INSTALL_ROOT}"

  mkdir -p "${INSTALL_ROOT}"

  if ! curl -fsSL "${archive_url}" -o "${tmp_dir}/encodr.tar.gz"; then
    archive_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${ref}.tar.gz"
    info "Tag archive not found, falling back to branch archive ${ref}"
    curl -fsSL "${archive_url}" -o "${tmp_dir}/encodr.tar.gz" || \
      fail "Unable to download Encodr from ${ref}."
  fi

  tar -xzf "${tmp_dir}/encodr.tar.gz" -C "${tmp_dir}" || fail "Downloaded archive could not be unpacked."
  local extracted_dir
  extracted_dir="$(find "${tmp_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "${extracted_dir}" ]] || fail "Downloaded archive could not be unpacked."

  mkdir -p "${INSTALL_ROOT}"
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
    if [[ ! -f "${INSTALL_ROOT}/docker-compose.yml" || ! -f "${INSTALL_ROOT}/.env.example" ]]; then
      download_release_tree
    else
      section "Using existing installation"
      info "Found an existing Encodr tree at ${INSTALL_ROOT}"
      success "Installer will reuse the existing installation files"
    fi
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
  set -a
  # shellcheck disable=SC1091
  source "${INSTALL_ROOT}/.env"
  set +a
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

  section "Preparing environment"
  install_base_packages
  ensure_docker

  ensure_release_tree
  cd "${INSTALL_ROOT}"

  section "Configuring Encodr"
  ./infra/scripts/bootstrap.sh >/dev/null
  mkdir -p "${STANDARD_MEDIA_ROOT}"
  ensure_secret "ENCODR_AUTH_SECRET"
  ensure_secret "ENCODR_WORKER_REGISTRATION_SECRET"

  mkdir -p /usr/local/bin
  ln -sf "${INSTALL_ROOT}/encodr" /usr/local/bin/encodr
  success "Installed the encodr management command"

  load_env

  section "Starting the stack"
  info "Launching Docker services"
  docker compose up -d --build >/dev/null || fail "Docker Compose could not start the Encodr stack."

  section "Verifying health"
  wait_for_health
  ./encodr doctor >/dev/null || fail "Encodr started, but the final doctor checks did not pass."
  success "Doctor checks passed"

  show_urls
}

main "$@"
