#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "${ROOT_DIR}"

LOCAL_CONFIG_FILES=(
  "config/app.yaml"
  "config/policy.yaml"
  "config/workers.yaml"
)
TEMP_BACKUPS=()

restore_local_config() {
  local backup original
  for backup in "${TEMP_BACKUPS[@]}"; do
    original="${backup%.release-check.bak}"
    mv "${backup}" "${original}"
  done
}

trap restore_local_config EXIT

for file in "${LOCAL_CONFIG_FILES[@]}"; do
  if [[ -f "${file}" ]]; then
    backup="${file}.release-check.bak"
    mv "${file}" "${backup}"
    TEMP_BACKUPS+=("${backup}")
  fi
done

echo "Running release validation for Encodr $(cat VERSION)"
make check

echo
echo "Manual release steps:"
echo "1. Confirm CHANGELOG.md and docs are up to date."
echo "2. Merge the approved branch to main."
echo "3. Tag the release, for example: git tag v$(cat VERSION)"
echo "4. Push main and the tag."
echo "5. Publish or update the release metadata source used for update checks."
