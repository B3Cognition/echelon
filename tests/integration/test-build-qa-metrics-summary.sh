#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
STATE_FILE="$ROOT_DIR/.specify/squad/state.json"
SCRIPT="$ROOT_DIR/extension/scripts/bash/phase-timing.sh"

if command -v bash >/dev/null 2>&1; then
  bash "$SCRIPT" record_split_metrics 2 1 1.00 --state-file "$STATE_FILE" || true
fi

grep -q '"split_metrics"' "$STATE_FILE"
grep -q '"qa_coverage"' "$STATE_FILE"

echo "build-qa metrics summary checks: PASS"
