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

set_local_dev_defaults() {
  python3 - "$ROOT_DIR/.env" "$ROOT_DIR/config/app.yaml" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
app_config_path = Path(sys.argv[2])

def replace_line(path: Path, key: str, value: str) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if not replaced and stripped.startswith(f"{key}:"):
            indent = line[: len(line) - len(line.lstrip())]
            updated.append(f"{indent}{key}: {value}")
            replaced = True
            continue
        if not replaced and stripped.startswith(f"{key}="):
            updated.append(f"{key}={value}")
            replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(f"{key}={value}" if path.suffix != ".yaml" else f"{key}: {value}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")

replace_line(env_path, "ENCODR_ENV", "development")
replace_line(app_config_path, "environment", "development")
PY
}

mkdir -p "$ROOT_DIR/.runtime" "$ROOT_DIR/.runtime/data"

if [[ "${EUID}" -eq 0 ]]; then
  mkdir -p /temp /media
else
  mkdir -p "$ROOT_DIR/.runtime/temp" "$ROOT_DIR/.runtime/media"
fi

copy_if_missing "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
copy_if_missing "$ROOT_DIR/config/app.example.yaml" "$ROOT_DIR/config/app.yaml"
copy_if_missing "$ROOT_DIR/config/policy.example.yaml" "$ROOT_DIR/config/policy.yaml"
copy_if_missing "$ROOT_DIR/config/workers.example.yaml" "$ROOT_DIR/config/workers.yaml"

if [[ "${EUID}" -ne 0 ]]; then
  set_local_dev_defaults
fi

cat <<'EOF'

Bootstrap complete.

Next steps:
1. Start the stack with `make dev-up` or `sudo ./install.sh`.
2. Open the UI and create the first admin user if prompted.
3. Mount your media library at `/media` when you are ready to work with real files.
4. Check access with `./encodr mount-setup --validate-only`.
EOF
