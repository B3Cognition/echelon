#!/usr/bin/env bash
# T-11: Integration test — parse SAGE contradiction report fixtures, validate required fields
set -euo pipefail

FIXTURES_DIR="$(cd "$(dirname "$0")/../.." && pwd)/tests/fixtures/agent-outputs/sage"
PASS=0
FAIL=0
TOTAL=0

assert_eq() {
  local label="$1" actual="$2" expected="$3"
  TOTAL=$((TOTAL + 1))
  if [ "$actual" = "$expected" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (expected '$expected', got '$actual')"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_empty() {
  local label="$1" value="$2"
  TOTAL=$((TOTAL + 1))
  if [ -n "$value" ] && [ "$value" != "null" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (value is empty or null)"
    FAIL=$((FAIL + 1))
  fi
}

# Check jq is available
if ! command -v jq &>/dev/null; then
  echo "SKIP: jq not installed"
  exit 0
fi

echo "=== SAGE Contradiction Report Format — Integration Tests ==="

# -------------------------------------------------------
# Positive report (has contradictions)
# -------------------------------------------------------
POS="$FIXTURES_DIR/contradiction-report-positive.json"
echo ""
echo "-- Positive report: $POS --"

# Validate JSON is parseable
TOTAL=$((TOTAL + 1))
if jq empty "$POS" 2>/dev/null; then
  echo "  PASS: Valid JSON"
  PASS=$((PASS + 1))
else
  echo "  FAIL: Invalid JSON"
  FAIL=$((FAIL + 1))
fi

# Check top-level contradiction_check fields
assert_eq "performed=true" "$(jq -r '.contradiction_check.performed' "$POS")" "true"
assert_not_empty "artifacts_scanned > 0" "$(jq -r '.contradiction_check.artifacts_scanned' "$POS")"
assert_not_empty "artifacts array" "$(jq -r '.contradiction_check.artifacts | length' "$POS")"
assert_not_empty "contradictions_found" "$(jq -r '.contradiction_check.contradictions_found' "$POS")"

# Check contradictions_found matches array length
FOUND=$(jq -r '.contradiction_check.contradictions_found' "$POS")
ARRAY_LEN=$(jq -r '.contradictions | length' "$POS")
assert_eq "contradictions_found matches array length" "$ARRAY_LEN" "$FOUND"

# Validate each contradiction has all 6 required fields
REQUIRED_FIELDS=("contradiction_type" "artifact_a" "artifact_b" "description" "severity" "suggested_resolution")
for i in $(seq 0 $((ARRAY_LEN - 1))); do
  for field in "${REQUIRED_FIELDS[@]}"; do
    val=$(jq -r ".contradictions[$i].\"$field\"" "$POS")
    assert_not_empty "contradictions[$i].$field" "$val"
  done
done

# Validate severity values are BLOCKING or WARNING
for i in $(seq 0 $((ARRAY_LEN - 1))); do
  sev=$(jq -r ".contradictions[$i].severity" "$POS")
  TOTAL=$((TOTAL + 1))
  if [ "$sev" = "BLOCKING" ] || [ "$sev" = "WARNING" ]; then
    echo "  PASS: contradictions[$i].severity is valid ($sev)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: contradictions[$i].severity is invalid ($sev)"
    FAIL=$((FAIL + 1))
  fi
done

# Validate contradiction_type values
VALID_TYPES="requirement_conflict assumption_requirement_misalignment boundary_violation priority_inversion acceptance_criteria_conflict"
for i in $(seq 0 $((ARRAY_LEN - 1))); do
  ctype=$(jq -r ".contradictions[$i].contradiction_type" "$POS")
  TOTAL=$((TOTAL + 1))
  if echo "$VALID_TYPES" | grep -qw "$ctype"; then
    echo "  PASS: contradictions[$i].contradiction_type is valid ($ctype)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: contradictions[$i].contradiction_type is invalid ($ctype)"
    FAIL=$((FAIL + 1))
  fi
done

# -------------------------------------------------------
# Zero report (no contradictions)
# -------------------------------------------------------
ZERO="$FIXTURES_DIR/contradiction-report-zero.json"
echo ""
echo "-- Zero report: $ZERO --"

# Validate JSON
TOTAL=$((TOTAL + 1))
if jq empty "$ZERO" 2>/dev/null; then
  echo "  PASS: Valid JSON"
  PASS=$((PASS + 1))
else
  echo "  FAIL: Invalid JSON"
  FAIL=$((FAIL + 1))
fi

assert_eq "performed=true" "$(jq -r '.contradiction_check.performed' "$ZERO")" "true"
assert_eq "contradictions_found=0" "$(jq -r '.contradiction_check.contradictions_found' "$ZERO")" "0"
assert_eq "contradictions array empty" "$(jq -r '.contradictions | length' "$ZERO")" "0"

# Check summary contains the "No contradictions detected across [N] artifacts" message
SUMMARY=$(jq -r '.summary' "$ZERO")
TOTAL=$((TOTAL + 1))
if echo "$SUMMARY" | grep -q "No contradictions detected across"; then
  echo "  PASS: summary contains 'No contradictions detected across [N] artifacts'"
  PASS=$((PASS + 1))
else
  echo "  FAIL: summary missing required message pattern"
  FAIL=$((FAIL + 1))
fi

# Check summary lists all 5 contradiction types
for ctype in requirement_conflict assumption_requirement_misalignment boundary_violation priority_inversion acceptance_criteria_conflict; do
  TOTAL=$((TOTAL + 1))
  if echo "$SUMMARY" | grep -q "$ctype"; then
    echo "  PASS: summary lists $ctype"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: summary missing $ctype"
    FAIL=$((FAIL + 1))
  fi
done

# Check artifacts_scanned matches artifacts array length
SCANNED=$(jq -r '.contradiction_check.artifacts_scanned' "$ZERO")
ARTIFACTS_LEN=$(jq -r '.contradiction_check.artifacts | length' "$ZERO")
assert_eq "artifacts_scanned matches array" "$ARTIFACTS_LEN" "$SCANNED"

echo ""
echo "=== Results: $PASS/$TOTAL passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "ALL CHECKS PASSED"
