#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run install.sh as root inside the target Debian LXC."
    exit 1
  fi
}

ensure_command() {
  local command_name="$1"
  shift
  if command -v "$command_name" >/dev/null 2>&1; then
    return
  fi
  "$@"
}

install_base_packages() {
  apt-get update
  apt-get install -y ca-certificates curl git jq gnupg lsb-release
}

install_docker() {
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

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

ensure_secret() {
  local variable_name="$1"
  if grep -q "^${variable_name}=change-me-before-production$" "${ROOT_DIR}/.env"; then
    local generated
    generated="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
    python3 - "${ROOT_DIR}/.env" "${variable_name}" "${generated}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
name = sys.argv[2]
value = sys.argv[3]
lines = env_path.read_text(encoding="utf-8").splitlines()
updated = [f"{name}={value}" if line.startswith(f"{name}=") else line for line in lines]
env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
    echo "Generated ${variable_name} in .env"
  fi
}

wait_for_health() {
  local url="http://127.0.0.1:8000/api/health"
  for _ in $(seq 1 30); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "API health check did not succeed at ${url}"
  return 1
}

show_urls() {
  local addresses
  addresses="$(hostname -I 2>/dev/null || true)"
  echo
  echo "Encodr services appear to be running."
  echo "API health: http://127.0.0.1:8000/api/health"
  echo "UI: http://127.0.0.1:5173"
  if [[ -n "${addresses// }" ]]; then
    echo "Detected IP addresses: ${addresses}"
  fi
  echo
  echo "Next steps:"
  echo "1. Open the UI and create the first admin user if prompted."
  echo "2. Review storage guidance with './encodr mount-setup'."
  echo "3. Run './encodr doctor' after mounting real media paths."
}

require_root
install_base_packages
ensure_command docker install_docker
if ! docker compose version >/dev/null 2>&1; then
  install_docker
fi

cd "${ROOT_DIR}"
./infra/scripts/bootstrap.sh
ensure_secret "ENCODR_AUTH_SECRET"
ensure_secret "ENCODR_WORKER_REGISTRATION_SECRET"

mkdir -p /usr/local/bin
ln -sf "${ROOT_DIR}/encodr" /usr/local/bin/encodr

docker compose up -d --build
wait_for_health
./encodr doctor
show_urls
