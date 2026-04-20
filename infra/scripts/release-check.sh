#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "${ROOT_DIR}"

echo "Running release validation for Encodr $(cat VERSION)"
make check

echo
echo "Manual release steps:"
echo "1. Confirm CHANGELOG.md and docs are up to date."
echo "2. Merge the approved branch to main."
echo "3. Tag the release, for example: git tag v$(cat VERSION)"
echo "4. Push main and the tag."
echo "5. Publish or update the release metadata source used for update checks."
