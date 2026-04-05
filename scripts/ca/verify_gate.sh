#!/usr/bin/env bash
# verify_gate.sh — CA Overlay Gate Check (T-020, FR-CAO-000)
#
# Performs exactly three checks in order:
#   1. experiments/uca004-results.json exists and is readable
#   2. verdict field equals "POSITIVE"
#   3. codebase_commit_hash matches git rev-parse HEAD
#
# Exit 0 if all three pass; exit 1 on first failure.
# Usage: verify_gate.sh [--verbose] [--results-file <path>]

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
VERBOSE=false
RESULTS_FILE=""

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose) VERBOSE=true ; shift ;;
    --results-file) RESULTS_FILE="$2" ; shift 2 ;;
    *) echo "Unknown argument: $1" >&2 ; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Locate repo root and derive default results path
# ---------------------------------------------------------------------------
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "GATE FAIL: git not found or not inside a git repository." >&2
  exit 1
}

if [[ -z "$RESULTS_FILE" ]]; then
  RESULTS_FILE="${GIT_ROOT}/experiments/uca004-results.json"
fi

# ---------------------------------------------------------------------------
# Check 1: results file exists and is readable
# ---------------------------------------------------------------------------
if [[ ! -f "$RESULTS_FILE" ]]; then
  echo "GATE FAIL: uca004-results.json not found at ${RESULTS_FILE}. Run uca004_runner.py first."
  exit 1
fi
if [[ ! -r "$RESULTS_FILE" ]]; then
  echo "GATE FAIL: uca004-results.json not found at ${RESULTS_FILE}. Run uca004_runner.py first."
  exit 1
fi

[[ "$VERBOSE" == "true" ]] && echo "CHECK 1 PASS: ${RESULTS_FILE} exists and is readable."

# ---------------------------------------------------------------------------
# Check 2: verdict == "POSITIVE"
# ---------------------------------------------------------------------------
VERDICT=$(python3 -c "
import json, sys
try:
    data = json.load(open('${RESULTS_FILE}'))
    print(data.get('verdict', 'MISSING'))
except Exception as e:
    print('READ_ERROR: ' + str(e))
    sys.exit(1)
" 2>/dev/null) || {
  echo "GATE FAIL: verdict is READ_ERROR, not POSITIVE. CA overlay implementation is blocked per P-020."
  exit 1
}

if [[ "$VERDICT" != "POSITIVE" ]]; then
  echo "GATE FAIL: verdict is ${VERDICT}, not POSITIVE. CA overlay implementation is blocked per P-020."
  exit 1
fi

[[ "$VERBOSE" == "true" ]] && echo "CHECK 2 PASS: verdict is POSITIVE."

# ---------------------------------------------------------------------------
# Check 3: commit hash matches current HEAD
# ---------------------------------------------------------------------------
CURRENT_HEAD=$(git rev-parse HEAD 2>/dev/null) || {
  echo "GATE FAIL: commit hash mismatch. Results were produced on <unknown>; current HEAD is <git-unavailable>. Re-run uca004_runner.py on the current codebase."
  exit 1
}

RESULTS_HASH=$(python3 -c "
import json
try:
    data = json.load(open('${RESULTS_FILE}'))
    print(data.get('codebase_commit_hash', 'MISSING'))
except Exception:
    print('READ_ERROR')
" 2>/dev/null)

if [[ "$RESULTS_HASH" != "$CURRENT_HEAD" ]]; then
  echo "GATE FAIL: commit hash mismatch. Results were produced on ${RESULTS_HASH}; current HEAD is ${CURRENT_HEAD}. Re-run uca004_runner.py on the current codebase."
  exit 1
fi

[[ "$VERBOSE" == "true" ]] && echo "CHECK 3 PASS: commit hash ${CURRENT_HEAD} matches."

# ---------------------------------------------------------------------------
# All checks passed
# ---------------------------------------------------------------------------
echo "GATE PASS: U-CA-004 verdict is POSITIVE, commit hash verified. CA overlay implementation is authorized."
exit 0
