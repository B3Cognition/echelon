#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
FIXTURE="$ROOT_DIR/tests/fixtures/state/build-qa-split-state-machine.json"

[ -f "$FIXTURE" ]

grep -q '"from": "QA_FAILED"' "$FIXTURE"
grep -q '"to": "REWORK_PLANNED"' "$FIXTURE"
grep -q '"to": "ESCALATED"' "$FIXTURE"
grep -q '"from": "CHANGE_PENDING"' "$FIXTURE"

echo "rework routing state-machine checks: PASS"
