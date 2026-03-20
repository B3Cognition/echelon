#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
CONTRACT="$ROOT_DIR/specs/002-build-qa-phase-split/contracts/build-qa-handoff.contract.yaml"
FIXTURE="$ROOT_DIR/tests/fixtures/state/build-qa-split-v040.json"

[ -f "$CONTRACT" ]
[ -f "$FIXTURE" ]

grep -q 'all_required_tasks_build_complete: true' "$CONTRACT"
grep -q 'required_blocked_task_count: 0' "$CONTRACT"
grep -q 'required_tasks_must_be_complete' "$CONTRACT"
grep -q 'required_blocked_forbidden' "$CONTRACT"

grep -q '"build_handoff_valid"' "$FIXTURE"
grep -q '"build_handoff_invalid_required_blocked"' "$FIXTURE"

echo "build-qa handoff contract checks: PASS"
