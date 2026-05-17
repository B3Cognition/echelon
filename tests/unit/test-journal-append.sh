#!/usr/bin/env bash
# Unit tests for extension/scripts/bash/journal-append.sh
# Tests: APP-01 through APP-06 per test-strategy.md
# Run: bash tests/unit/test-journal-append.sh

set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT_DIR/extension/scripts/bash/journal-append.sh"
FIXTURES="$ROOT_DIR/tests/fixtures/journal-entries"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PASS=0
FAIL=0

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (expected: $expected, got: $actual)"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" output="$2" needle="$3"
  if echo "$output" | grep -qF "$needle"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (expected to contain: $needle)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== APP-01: Valid entry appended, no warning ==="
JOURNAL="$TMP_DIR/app01.jsonl"
VALID_ENTRY=$(cat "$FIXTURES/valid-routing-decision.json")
set +e
bash "$SCRIPT" --entry "$VALID_ENTRY" --journal-path "$JOURNAL" 2>/dev/null
RC=$?
set -e
assert_eq "APP-01 exit code" "0" "$RC"
LINE_COUNT=$(wc -l < "$JOURNAL")
assert_eq "APP-01 line count" "1" "$LINE_COUNT"
# Verify no schema_warning line
set +e
WARNING_COUNT=$(grep -c '"schema_warning"' "$JOURNAL" 2>/dev/null)
set -e
WARNING_COUNT="${WARNING_COUNT:-0}"
# Trim whitespace
WARNING_COUNT=$(echo "$WARNING_COUNT" | tr -d '[:space:]')
assert_eq "APP-01 no schema_warning" "0" "$WARNING_COUNT"

echo ""
echo "=== APP-02: Invalid entry still appended + warning sibling ==="
JOURNAL="$TMP_DIR/app02.jsonl"
INVALID_ENTRY=$(cat "$FIXTURES/invalid-missing-field.json")
set +e
bash "$SCRIPT" --entry "$INVALID_ENTRY" --journal-path "$JOURNAL" 2>/dev/null
RC=$?
set -e
assert_eq "APP-02 exit code" "0" "$RC"
LINE_COUNT=$(wc -l < "$JOURNAL")
assert_eq "APP-02 line count" "2" "$LINE_COUNT"
# First line is the original entry
FIRST_TYPE=$(head -1 "$JOURNAL" | jq -r '.type')
assert_eq "APP-02 first line is original entry" "routing_decision" "$FIRST_TYPE"
# Second line is schema_warning
SECOND_TYPE=$(tail -1 "$JOURNAL" | jq -r '.type')
assert_eq "APP-02 second line is schema_warning" "schema_warning" "$SECOND_TYPE"

echo ""
echo "=== APP-03: Warning entry structure ==="
JOURNAL="$TMP_DIR/app03.jsonl"
bash "$SCRIPT" --entry "$INVALID_ENTRY" --journal-path "$JOURNAL" 2>/dev/null || true
WARNING_LINE=$(tail -1 "$JOURNAL")
# Verify required fields
VID=$(echo "$WARNING_LINE" | jq -r '.data.violating_entry_id')
VTYPE=$(echo "$WARNING_LINE" | jq -r '.data.violation_type')
DETAILS=$(echo "$WARNING_LINE" | jq -r '.data.details')
assert_eq "APP-03 has violating_entry_id" "RJ-044" "$VID"
if [ -n "$VTYPE" ] && [ "$VTYPE" != "null" ]; then
  echo "  PASS: APP-03 has violation_type ($VTYPE)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: APP-03 missing violation_type"
  FAIL=$((FAIL + 1))
fi
if [ -n "$DETAILS" ] && [ "$DETAILS" != "null" ]; then
  echo "  PASS: APP-03 has details ($DETAILS)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: APP-03 missing details"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "=== APP-04: Always exits 0 ==="
# Test with valid entry
JOURNAL="$TMP_DIR/app04a.jsonl"
set +e
bash "$SCRIPT" --entry "$VALID_ENTRY" --journal-path "$JOURNAL" 2>/dev/null
RC1=$?
set -e
assert_eq "APP-04a valid entry exits 0" "0" "$RC1"
# Test with invalid entry
JOURNAL="$TMP_DIR/app04b.jsonl"
set +e
bash "$SCRIPT" --entry "$INVALID_ENTRY" --journal-path "$JOURNAL" 2>/dev/null
RC2=$?
set -e
assert_eq "APP-04b invalid entry exits 0" "0" "$RC2"
# Test with unknown type
UNKNOWN='{"id":"RJ-099","type":"nonexistent_type","phase":"p","agent":"a","timestamp":"2025-01-01T00:00:00Z","data":{"x":"y"}}'
JOURNAL="$TMP_DIR/app04c.jsonl"
set +e
bash "$SCRIPT" --entry "$UNKNOWN" --journal-path "$JOURNAL" 2>/dev/null
RC3=$?
set -e
assert_eq "APP-04c unknown type exits 0" "0" "$RC3"

echo ""
echo "=== APP-05: Creates journal file if missing ==="
JOURNAL="$TMP_DIR/subdir/new-journal.jsonl"
# subdir does not exist yet either
mkdir -p "$(dirname "$JOURNAL")"
set +e
bash "$SCRIPT" --entry "$VALID_ENTRY" --journal-path "$JOURNAL" 2>/dev/null
RC=$?
set -e
assert_eq "APP-05 exit code" "0" "$RC"
if [ -f "$JOURNAL" ]; then
  echo "  PASS: APP-05 journal file created"
  PASS=$((PASS + 1))
else
  echo "  FAIL: APP-05 journal file not created"
  FAIL=$((FAIL + 1))
fi
LINE_COUNT=$(wc -l < "$JOURNAL")
assert_eq "APP-05 entry appended" "1" "$LINE_COUNT"

echo ""
echo "=== APP-06: tool_output_ref cross-check ==="
TOOL_ENTRY='{"id":"RJ-060","type":"quality_check","phase":"phase2-why2","agent":"speckit-echelon-sage","timestamp":"2025-01-15T10:00:00Z","data":{"pass":1,"scores":{"structure":0.8},"issues":[],"source":"tool:understanding.validate"}}'
JOURNAL="$TMP_DIR/app06.jsonl"
set +e
STDERR_OUT=$(bash "$SCRIPT" --entry "$TOOL_ENTRY" --journal-path "$JOURNAL" 2>&1 >/dev/null)
RC=$?
set -e
assert_eq "APP-06 exit code" "0" "$RC"
# Verify entry still appended
LINE_COUNT=$(wc -l < "$JOURNAL")
if [ "$LINE_COUNT" -ge 1 ]; then
  echo "  PASS: APP-06 entry appended despite missing ref"
  PASS=$((PASS + 1))
else
  echo "  FAIL: APP-06 entry not appended"
  FAIL=$((FAIL + 1))
fi
# Verify stderr warning about missing tool_output_ref
if echo "$STDERR_OUT" | grep -qi "tool_output_ref\|missing"; then
  echo "  PASS: APP-06 stderr warns about missing ref"
  PASS=$((PASS + 1))
else
  echo "  FAIL: APP-06 no stderr warning about missing ref"
  echo "        stderr: $STDERR_OUT"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "═══════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
