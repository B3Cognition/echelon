#!/usr/bin/env bash
# Validate Echelon's canonical Prosaic prose and runtime bundles.
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"
INPUT_ROOT="${1:-$SOURCE_ROOT}"

if [[ -x "$SOURCE_ROOT/.venv/bin/python" ]]; then
  PYTHON="$SOURCE_ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="$SOURCE_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m harness.bundle_validator "$INPUT_ROOT"
