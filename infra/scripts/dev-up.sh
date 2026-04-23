#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f ".env" ]]; then
  echo ".env is missing. Run ./infra/scripts/bootstrap.sh first."
  exit 1
fi

if [[ -f "./infra/scripts/generate_runtime_compose.py" ]]; then
  python3 ./infra/scripts/generate_runtime_compose.py --project-root . >/dev/null
fi

compose_args=(-f docker-compose.yml)
if [[ -f "./infra/compose/local.override.yml" ]]; then
  compose_args+=(-f ./infra/compose/local.override.yml)
fi
if [[ -f "./.runtime/compose.runtime.yml" ]]; then
  compose_args+=(-f ./.runtime/compose.runtime.yml)
fi

docker compose "${compose_args[@]}" up --build
