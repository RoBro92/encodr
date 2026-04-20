#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

copy_if_missing() {
  local source_file="$1"
  local target_file="$2"
  if [[ -f "$target_file" ]]; then
    echo "Exists: ${target_file#$ROOT_DIR/}"
    return
  fi

  cp "$source_file" "$target_file"
  echo "Created: ${target_file#$ROOT_DIR/}"
}

mkdir -p "$ROOT_DIR/.runtime" "$ROOT_DIR/scratch"

copy_if_missing "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
copy_if_missing "$ROOT_DIR/config/app.example.yaml" "$ROOT_DIR/config/app.yaml"
copy_if_missing "$ROOT_DIR/config/policy.example.yaml" "$ROOT_DIR/config/policy.yaml"
copy_if_missing "$ROOT_DIR/config/workers.example.yaml" "$ROOT_DIR/config/workers.yaml"

cat <<'EOF'

Bootstrap complete.

Next steps:
1. Review `.env` and set `ENCODR_AUTH_SECRET` and `ENCODR_WORKER_REGISTRATION_SECRET`.
2. Review `config/app.yaml`, `config/policy.yaml`, and `config/workers.yaml`.
3. Start dependencies with `make dev-up`.
4. Run the API, worker, and UI locally as needed with `make api`, `make worker`, and `make ui`.
EOF
