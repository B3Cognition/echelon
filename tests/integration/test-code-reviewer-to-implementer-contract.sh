#!/usr/bin/env bash
# T-08: Integration test — parse consolidated review fixture, verify all required fields
# Validates that the code-reviewer output contract matches what IMPLEMENTER expects.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FIXTURE="$REPO_ROOT/tests/fixtures/code-reviewer/review-consolidated.json"

PASS=0
FAIL=0

# Requires jq
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

echo "=== CODE REVIEWER → IMPLEMENTER Contract Integration Test ==="
echo "Fixture: $FIXTURE"
echo ""

# --- Top-level fields ---
echo "[1] Top-level contract fields"
assert_field "task_id present" '.task_id | length > 0'
assert_field "task_title present" '.task_title | length > 0'
assert_field "verdict is valid" '.verdict | test("APPROVED|CHANGES_REQUESTED|BLOCKED")'
assert_field "findings is array" '.findings | type == "array"'
assert_field "summary is array" '.summary | type == "array"'

# --- Finding fields (iterate all findings) ---
echo ""
echo "[2] Finding-level required fields"
FINDING_COUNT=$(jq '.findings | length' "$FIXTURE")
echo "   (checking $FINDING_COUNT findings)"

for i in $(seq 0 $((FINDING_COUNT - 1))); do
  echo "  --- Finding $((i + 1)) ---"
  assert_field "  confidence present" ".findings[$i].confidence | type == \"number\""
  assert_field "  confidence > 80" ".findings[$i].confidence > 80"
  assert_field "  severity present" ".findings[$i].severity | test(\"CRITICAL|HIGH|MEDIUM\")"
  assert_field "  file_line present" ".findings[$i].file_line | length > 0"
  assert_field "  category present" ".findings[$i].category | length > 0"
  assert_field "  description present" ".findings[$i].description | length > 0"
  assert_field "  suggested_fix present" ".findings[$i].suggested_fix | length > 0"
done

# --- Summary table structure ---
echo ""
echo "[3] Summary table structure"
assert_field "summary has CRITICAL row" '.summary[] | select(.severity == "CRITICAL") | .count >= 0'
assert_field "summary has HIGH row" '.summary[] | select(.severity == "HIGH") | .count >= 0'
assert_field "summary has MEDIUM row" '.summary[] | select(.severity == "MEDIUM") | .count >= 0'
assert_field "summary status values valid" '[.summary[].status] | all(test("PASS|FAIL|INFO"))'

# --- Verdict consistency ---
echo ""
echo "[4] Verdict consistency with findings"
HAS_CRITICAL=$(jq '[.findings[].severity] | any(. == "CRITICAL")' "$FIXTURE")
HAS_HIGH=$(jq '[.findings[].severity] | any(. == "HIGH")' "$FIXTURE")
VERDICT=$(jq -r '.verdict' "$FIXTURE")

if [ "$HAS_CRITICAL" = "true" ]; then
  if [ "$VERDICT" = "BLOCKED" ]; then
    echo "  PASS: CRITICAL findings -> BLOCKED verdict"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: CRITICAL findings present but verdict is $VERDICT (expected BLOCKED)"
    FAIL=$((FAIL + 1))
  fi
elif [ "$HAS_HIGH" = "true" ]; then
  if [ "$VERDICT" = "CHANGES_REQUESTED" ]; then
    echo "  PASS: HIGH findings -> CHANGES_REQUESTED verdict"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: HIGH findings present but verdict is $VERDICT (expected CHANGES_REQUESTED)"
    FAIL=$((FAIL + 1))
  fi
else
  if [ "$VERDICT" = "APPROVED" ]; then
    echo "  PASS: No HIGH/CRITICAL -> APPROVED verdict"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: No HIGH/CRITICAL but verdict is $VERDICT (expected APPROVED)"
    FAIL=$((FAIL + 1))
  fi
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "All checks passed."
