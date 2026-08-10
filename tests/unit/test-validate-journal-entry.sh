#!/usr/bin/env bash
# Unit tests for runtime/scripts/bash/validate-journal-entry.sh
# Tests: VLD-01 through VLD-10 per test-strategy.md
# Run: bash tests/unit/test-validate-journal-entry.sh

set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT_DIR/runtime/scripts/bash/validate-journal-entry.sh"
FIXTURES="$ROOT_DIR/tests/fixtures/journal-entries"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PASS=0
FAIL=0

assert_exit_code() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" -eq "$expected" ]; then
    echo "  PASS: $label (exit $actual)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (exit $actual — expected $expected)"
    FAIL=$((FAIL + 1))
  fi
}

assert_json_field() {
  local label="$1" json="$2" field="$3" expected="$4"
  local actual
  actual=$(printf '%s' "$json" | jq -r "$field" 2>/dev/null)
  if [ "$actual" = "$expected" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        Expected $field = $expected, got: $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_json_nonempty() {
  local label="$1" json="$2" field="$3"
  local length
  length=$(printf '%s' "$json" | jq "$field | length" 2>/dev/null)
  if [ "$length" -gt 0 ] 2>/dev/null; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label ($field is empty)"
    FAIL=$((FAIL + 1))
  fi
}

assert_json_empty() {
  local label="$1" json="$2" field="$3"
  local length
  length=$(printf '%s' "$json" | jq "$field | length" 2>/dev/null)
  if [ "$length" -eq 0 ] 2>/dev/null; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label ($field is not empty)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== VLD-01: Valid routing_decision passes ==="
OUTPUT=$(cat "$FIXTURES/valid-routing-decision.json" | bash "$SCRIPT" 2>/dev/null) || true
RC=$?
# Capture exit code correctly — need to re-run since set -e
set +e
OUTPUT=$(cat "$FIXTURES/valid-routing-decision.json" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-01 exit code" 0 "$RC"
assert_json_field "VLD-01 valid=true" "$OUTPUT" ".valid" "true"
assert_json_field "VLD-01 entry_type" "$OUTPUT" ".entry_type" "routing_decision"

echo ""
echo "=== VLD-02: Missing required field fails ==="
set +e
OUTPUT=$(cat "$FIXTURES/invalid-missing-field.json" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-02 exit code" 1 "$RC"
assert_json_field "VLD-02 valid=false" "$OUTPUT" ".valid" "false"
assert_json_nonempty "VLD-02 errors non-empty" "$OUTPUT" ".errors"

echo ""
echo "=== VLD-03: Extra fields produce warning ==="
EXTRA_ENTRY='{"id":"RJ-050","type":"routing_decision","phase":"phase2-how","agent":"speckit-echelon-commander","timestamp":"2025-01-15T10:30:00Z","data":{"from_phase":"phase1-why1","to_phase":"phase2-how","reason":"test","evoi_score":0.5,"my_custom_field":"extra"}}'
set +e
OUTPUT=$(printf '%s' "$EXTRA_ENTRY" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-03 exit code" 0 "$RC"
assert_json_field "VLD-03 valid=true" "$OUTPUT" ".valid" "true"
assert_json_nonempty "VLD-03 warnings non-empty" "$OUTPUT" ".warnings"

echo ""
echo "=== VLD-04: Unknown type passes with warning ==="
UNKNOWN_ENTRY='{"id":"RJ-051","type":"does_not_exist","phase":"phase1","agent":"x","timestamp":"2025-01-01T00:00:00Z","data":{"foo":"bar"}}'
set +e
OUTPUT=$(printf '%s' "$UNKNOWN_ENTRY" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-04 exit code" 2 "$RC"
assert_json_field "VLD-04 valid=true" "$OUTPUT" ".valid" "true"
assert_json_nonempty "VLD-04 warnings mention unregistered" "$OUTPUT" ".warnings"

echo ""
echo "=== VLD-05: Entry >1MB rejected ==="
# Generate a 1.1MB JSON blob
LARGE_VALUE=$(python3 -c "print('x' * 1200000)")
LARGE_ENTRY="{\"id\":\"RJ-052\",\"type\":\"insight\",\"phase\":\"p\",\"agent\":\"a\",\"timestamp\":\"2025-01-01T00:00:00Z\",\"data\":{\"artifact\":\"$LARGE_VALUE\",\"section\":\"s\",\"reasoning\":\"r\",\"confidence\":0.5,\"evidence_grade\":\"low\"}}"
set +e
OUTPUT=$(printf '%s' "$LARGE_ENTRY" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-05 exit code" 1 "$RC"

echo ""
echo "=== VLD-06: Malformed JSON handled ==="
set +e
OUTPUT=$(cat "$FIXTURES/invalid-malformed.json" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-06 exit code" 1 "$RC"
assert_json_field "VLD-06 valid=false" "$OUTPUT" ".valid" "false"

echo ""
echo "=== VLD-07: Performance under budget (100 invocations < 100ms each) ==="
VALID_ENTRY=$(cat "$FIXTURES/valid-routing-decision.json")
START_NS=$(date +%s%N)
for i in $(seq 1 100); do
  printf '%s' "$VALID_ENTRY" | bash "$SCRIPT" >/dev/null 2>&1 || true
done
END_NS=$(date +%s%N)
TOTAL_MS=$(( (END_NS - START_NS) / 1000000 ))
AVG_MS=$(( TOTAL_MS / 100 ))
if [ "$AVG_MS" -lt 100 ]; then
  echo "  PASS: VLD-07 avg ${AVG_MS}ms per invocation (< 100ms)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: VLD-07 avg ${AVG_MS}ms per invocation (>= 100ms)"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "=== VLD-08: Missing schema file error ==="
set +e
OUTPUT=$(SCHEMA_PATH="/nonexistent/path.json" printf '%s' "$VALID_ENTRY" | bash "$SCRIPT" 2>"$TMP_DIR/stderr08.txt")
RC=$?
# Re-run with explicit SCHEMA_PATH
OUTPUT=$(SCHEMA_PATH="/nonexistent/path.json" bash "$SCRIPT" "$VALID_ENTRY" 2>"$TMP_DIR/stderr08.txt")
RC=$?
set -e
assert_exit_code "VLD-08 exit code" 2 "$RC"
STDERR08=$(cat "$TMP_DIR/stderr08.txt")
if echo "$STDERR08" | grep -qi "schema\|not readable\|unreadable\|ERROR"; then
  echo "  PASS: VLD-08 stderr has informative message"
  PASS=$((PASS + 1))
else
  echo "  FAIL: VLD-08 stderr missing informative message"
  echo "        stderr: $STDERR08"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "=== VLD-09: tool_output_ref cross-check ==="
TOOL_ENTRY='{"id":"RJ-053","type":"quality_check","phase":"phase2-why2","agent":"speckit-echelon-sage","timestamp":"2025-01-15T10:00:00Z","data":{"pass":1,"scores":{"structure":0.8},"issues":[],"source":"tool:understanding.validate"}}'
set +e
OUTPUT=$(printf '%s' "$TOOL_ENTRY" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-09 exit code" 0 "$RC"
assert_json_nonempty "VLD-09 warnings about missing ref" "$OUTPUT" ".warnings"

echo ""
echo "=== VLD-10: schema_warning type validates ==="
set +e
OUTPUT=$(cat "$FIXTURES/valid-schema-warning.json" | bash "$SCRIPT" 2>/dev/null)
RC=$?
set -e
assert_exit_code "VLD-10 exit code" 0 "$RC"
assert_json_field "VLD-10 valid=true" "$OUTPUT" ".valid" "true"

echo ""
echo "═══════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
