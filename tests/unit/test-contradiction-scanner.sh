#!/usr/bin/env sh
# test-contradiction-scanner.sh — Unit tests for scripts/contradiction-scanner.py
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SCRIPT="$ROOT_DIR/extension/scripts/contradiction-scanner.py"
FIXTURES="$ROOT_DIR/tests/fixtures/contradiction-scanner"
TMP_DIR="$(mktemp -d)"

PASS=0
FAIL=0
TOTAL=0

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

assert_ok() {
  label="$1"
  TOTAL=$((TOTAL + 1))
  if eval "$2" >/dev/null 2>&1; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    FAIL=$((FAIL + 1))
  fi
}

assert_json_key() {
  label="$1"
  file="$2"
  key="$3"
  TOTAL=$((TOTAL + 1))
  if python3 -c "import json,sys; d=json.load(open('$file')); assert '$key' in d, '$key missing'" 2>/dev/null; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (key '$key' not found in $file)"
    FAIL=$((FAIL + 1))
  fi
}

assert_json_val() {
  label="$1"
  file="$2"
  expr="$3"
  TOTAL=$((TOTAL + 1))
  if python3 -c "import json,sys; d=json.load(open('$file')); $expr" 2>/dev/null; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (expression: $expr)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== contradiction-scanner.py — Unit Tests ==="
echo ""

# ---------------------------------------------------------------------------
# Test 1: --help exits 0
# ---------------------------------------------------------------------------
echo "-- Test 1: --help exits 0 --"
assert_ok "--help exits 0" "python3 '$SCRIPT' --help"
echo ""

# ---------------------------------------------------------------------------
# Test 2: Clean fixture — produces valid JSON
# ---------------------------------------------------------------------------
echo "-- Test 2: Clean fixture produces valid JSON --"

CLEAN_OUT="$TMP_DIR/clean-report.json"
CLEAN_SPECS="$FIXTURES/clean-run/.."   # parent of clean-run = contradiction-scanner/

python3 "$SCRIPT" \
  --specs-dir "$FIXTURES" \
  --spec-ids "clean-run" \
  --output "$CLEAN_OUT" 2>/dev/null

assert_ok "Output file exists" "[ -f '$CLEAN_OUT' ]"
assert_ok "Output is valid JSON" "python3 -c \"import json; json.load(open('$CLEAN_OUT'))\""
echo ""

# ---------------------------------------------------------------------------
# Test 3: Required top-level keys present in output
# ---------------------------------------------------------------------------
echo "-- Test 3: Required top-level keys present --"

REQUIRED_KEYS="run_id spec_ids_scanned scanned_at detection_method bound_type \
method_limitations pairs_scanned contradictions_detected contradiction_rate_per_run \
per_pair_rates contradictions manual_precision_sample"

for key in $REQUIRED_KEYS; do
  assert_json_key "Key: $key" "$CLEAN_OUT" "$key"
done
echo ""

# ---------------------------------------------------------------------------
# Test 4: Dirty fixture — injected contradiction (42 vs 19 agents) is detected
# ---------------------------------------------------------------------------
echo "-- Test 4: Dirty fixture — injected count contradiction detected --"

DIRTY_OUT="$TMP_DIR/dirty-report.json"

python3 "$SCRIPT" \
  --specs-dir "$FIXTURES" \
  --spec-ids "dirty-run" \
  --output "$DIRTY_OUT" 2>/dev/null

assert_ok "Dirty output file exists" "[ -f '$DIRTY_OUT' ]"
assert_json_val \
  "contradictions_detected > 0 (42 vs 19 mismatch caught)" \
  "$DIRTY_OUT" \
  "assert d['contradictions_detected'] > 0, f\"expected >0, got {d['contradictions_detected']}\""
assert_json_val \
  "At least one contradiction type is count_mismatch" \
  "$DIRTY_OUT" \
  "assert any(c['type']=='count_mismatch' for c in d['contradictions']), 'no count_mismatch found'"
echo ""

# ---------------------------------------------------------------------------
# Test 5: Clean fixture — zero contradictions
# ---------------------------------------------------------------------------
echo "-- Test 5: Clean fixture — contradictions_detected is 0 --"

assert_json_val \
  "contradictions_detected == 0 on clean fixture" \
  "$CLEAN_OUT" \
  "assert d['contradictions_detected'] == 0, f\"expected 0, got {d['contradictions_detected']}\""
echo ""

# ---------------------------------------------------------------------------
# Test 6: bound_type is upper_bound
# ---------------------------------------------------------------------------
echo "-- Test 6: bound_type is 'upper_bound' --"
assert_json_val \
  "bound_type == upper_bound" \
  "$DIRTY_OUT" \
  "assert d['bound_type'] == 'upper_bound', f\"got {d['bound_type']}\""
echo ""

# ---------------------------------------------------------------------------
# Test 7: manual_precision_sample has verified=null entries
# ---------------------------------------------------------------------------
echo "-- Test 7: manual_precision_sample entries have verified=null --"
assert_json_val \
  "manual_precision_sample[0].verified is null (dirty fixture has sample)" \
  "$DIRTY_OUT" \
  "s=d.get('manual_precision_sample',[]); assert len(s)==0 or s[0]['verified'] is None"
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "=== Results: $PASS/$TOTAL passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "ALL CHECKS PASSED"
