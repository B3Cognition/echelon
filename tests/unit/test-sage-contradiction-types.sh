#!/usr/bin/env bash
# T-10: Unit test — verify SAGE spec contains all 5 contradiction types and report format template
set -euo pipefail

SAGE_MD="$(cd "$(dirname "$0")/../.." && pwd)/agents/exploration/sage.md"
PASS=0
FAIL=0
TOTAL=0

assert_grep() {
  local label="$1"
  local pattern="$2"
  TOTAL=$((TOTAL + 1))
  if grep -qiE "$pattern" "$SAGE_MD"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (pattern not found: $pattern)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== SAGE Contradiction Detection — Unit Tests ==="
echo "File: $SAGE_MD"
echo ""

# --- 5 contradiction types ---
echo "-- Contradiction types --"
assert_grep "Type 1: Requirement conflicts" "requirement.conflicts"
assert_grep "Type 2: Assumption-requirement misalignment" "assumption.requirement.misalignment"
assert_grep "Type 3: Boundary violations" "boundary.violations"
assert_grep "Type 4: Priority inversions" "priority.inversions"
assert_grep "Type 5: Acceptance criteria conflicts" "acceptance.criteria.conflicts"

# --- Report format fields ---
echo ""
echo "-- Report format fields --"
assert_grep "Field: contradiction_type" "contradiction_type"
assert_grep "Field: artifact_a" "artifact_a"
assert_grep "Field: artifact_b" "artifact_b"
assert_grep "Field: description" "description"
assert_grep "Field: severity" "severity"
assert_grep "Field: suggested_resolution" "suggested_resolution"

# --- Severity values ---
echo ""
echo "-- Severity values --"
assert_grep "Severity BLOCKING" "BLOCKING"
assert_grep "Severity WARNING" "WARNING"

# --- Zero-contradiction message ---
echo ""
echo "-- Zero-contradiction handling --"
assert_grep "Zero contradictions message" "No contradictions detected across"
assert_grep "Logging requirement" "log.*contradiction check was performed|Always log that the contradiction check"

# --- Section exists ---
echo ""
echo "-- Section header --"
assert_grep "Section header present" "Systematic Contradiction Detection"

echo ""
echo "=== Results: $PASS/$TOTAL passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "ALL CHECKS PASSED"
