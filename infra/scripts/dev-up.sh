#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f ".env" ]]; then
  echo ".env is missing. Run ./infra/scripts/bootstrap.sh first."
  exit 1
fi

docker compose up --build
