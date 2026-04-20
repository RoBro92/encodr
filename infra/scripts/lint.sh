#!/usr/bin/env bash
set -euo pipefail

python3 -m compileall apps packages tests >/dev/null
echo "Compile checks passed."
echo "Ruff, mypy, and dedicated frontend linting are still out of scope for this release."
