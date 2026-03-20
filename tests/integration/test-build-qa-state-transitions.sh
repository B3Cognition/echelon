#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
FIXTURE="$ROOT_DIR/tests/fixtures/state/build-qa-split-state-machine.json"

require_transition() {
  from="$1"
  to="$2"
  if ! grep -q "\"from\": \"$from\"" "$FIXTURE"; then
    echo "missing transition origin: $from" >&2
    exit 1
  fi
  if ! grep -q "\"to\": \"$to\"" "$FIXTURE"; then
    echo "missing transition target: $to" >&2
    exit 1
  fi
}

require_transition "TODO" "BUILD_IN_PROGRESS"
require_transition "BUILD_IN_PROGRESS" "BUILD_COMPLETE"
require_transition "BUILD_COMPLETE" "QA_IN_PROGRESS"
require_transition "QA_IN_PROGRESS" "QA_COMPLETE"
require_transition "QA_IN_PROGRESS" "CHANGE_PENDING"
require_transition "QA_FAILED" "REWORK_PLANNED"
require_transition "QA_FAILED" "ESCALATED"

echo "build-qa state transition fixture checks: PASS"