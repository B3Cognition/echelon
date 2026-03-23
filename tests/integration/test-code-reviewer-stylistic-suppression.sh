#!/usr/bin/env bash
# T-08: Integration test — verify stylistic-only reviews are identified as suppressible
# Validates that stylistic findings are suppressed and verdict remains APPROVED.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FIXTURE="$REPO_ROOT/tests/fixtures/code-reviewer/review-stylistic-only.json"

PASS=0
FAIL=0

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required but not installed."
  exit 2
fi

assert_field() {
  local label="$1"
  local jq_expr="$2"
  local result
  result=$(jq -e "$jq_expr" "$FIXTURE" 2>/dev/null) || true
  if [ -n "$result" ] && [ "$result" != "null" ] && [ "$result" != "false" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (jq: $jq_expr)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== CODE REVIEWER Stylistic Suppression Integration Test ==="
echo "Fixture: $FIXTURE"
echo ""

# --- Verdict must be APPROVED when only stylistic findings ---
echo "[1] Verdict for stylistic-only review"
assert_field "verdict is APPROVED" '.verdict == "APPROVED"'

# --- No real findings reported ---
echo ""
echo "[2] No actionable findings in output"
assert_field "findings array is empty" '.findings | length == 0'

# --- Suppressed stylistic findings present ---
echo ""
echo "[3] Suppressed stylistic findings tracked"
assert_field "suppressed_stylistic is array" '.suppressed_stylistic | type == "array"'
assert_field "at least 1 suppressed finding" '.suppressed_stylistic | length > 0'

SUPPRESSED_COUNT=$(jq '.suppressed_stylistic | length' "$FIXTURE")
echo "   (checking $SUPPRESSED_COUNT suppressed findings)"

for i in $(seq 0 $((SUPPRESSED_COUNT - 1))); do
  echo "  --- Suppressed finding $((i + 1)) ---"
  assert_field "  severity is STYLE" ".suppressed_stylistic[$i].severity == \"STYLE\""
  assert_field "  file_line present" ".suppressed_stylistic[$i].file_line | length > 0"
  assert_field "  reason_suppressed present" ".suppressed_stylistic[$i].reason_suppressed | length > 0"
  assert_field "  reason mentions stylistic" ".suppressed_stylistic[$i].reason_suppressed | test(\"[Ss]tylistic\")"
done

# --- Summary table shows all zeros ---
echo ""
echo "[4] Summary table — all severities at zero"
assert_field "CRITICAL count is 0" '.summary[] | select(.severity == "CRITICAL") | .count == 0'
assert_field "HIGH count is 0" '.summary[] | select(.severity == "HIGH") | .count == 0'
assert_field "MEDIUM count is 0" '.summary[] | select(.severity == "MEDIUM") | .count == 0'
assert_field "all statuses PASS" '[.summary[].status] | all(. == "PASS")'

# --- Confidence values are below threshold (these were suppressed for a reason) ---
echo ""
echo "[5] Suppressed findings have sub-threshold or stylistic confidence"
assert_field "all suppressed below 80" '[.suppressed_stylistic[].confidence] | all(. < 80)'

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "All checks passed."
