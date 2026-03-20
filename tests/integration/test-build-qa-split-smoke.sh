#!/usr/bin/env sh
set -eu

SCRIPT_DIR="${0%/*}"
if [ "$SCRIPT_DIR" = "$0" ]; then
  SCRIPT_DIR="."
fi
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"

assert_file() {
  path="$1"
  if [ ! -f "$path" ]; then
    echo "missing required file: $path" >&2
    exit 1
  fi
}

assert_file "$ROOT_DIR/tests/utils/validate-contracts.sh"
assert_file "$ROOT_DIR/tests/fixtures/state/build-qa-split-v040.json"
assert_file "$ROOT_DIR/specs/002-build-qa-phase-split/contracts/build-qa-handoff.contract.yaml"
assert_file "$ROOT_DIR/specs/002-build-qa-phase-split/contracts/rework-loop-transition.contract.yaml"

echo "build-qa-split smoke: PASS"
