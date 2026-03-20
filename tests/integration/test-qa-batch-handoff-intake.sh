#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
CONTRACT="$ROOT_DIR/specs/002-build-qa-phase-split/contracts/build-qa-handoff.contract.yaml"
FIXTURE="$ROOT_DIR/tests/fixtures/state/build-qa-split-v040.json"

[ -f "$CONTRACT" ]
[ -f "$FIXTURE" ]

grep -q 'required_blocked_task_count: 0' "$CONTRACT"
grep -q 'failure_action: reject_handoff' "$CONTRACT"

grep -q '"build_handoff_valid"' "$FIXTURE"
grep -q '"build_handoff_invalid_required_blocked"' "$FIXTURE"

echo "qa batch handoff intake checks: PASS"
