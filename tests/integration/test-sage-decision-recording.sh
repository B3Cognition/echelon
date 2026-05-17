#!/usr/bin/env bash
# T-18 Integration Test: Validate sage-decisions.yaml with sample entries
# Creates a fixture file with sample entries and validates all required fields.
# Usage: bash tests/integration/test-sage-decision-recording.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIXTURE_DIR=$(mktemp -d)
FIXTURE_FILE="$FIXTURE_DIR/sage-decisions.yaml"
PASS=0
FAIL=0

# NOTE: `((PASS++))` returns the OLD value (0 initially), which is falsy
# arithmetic and trips `set -e`, causing the script to exit silently after
# the first PASS. Use plain arithmetic assignment instead.
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

cleanup() { rm -rf "$FIXTURE_DIR"; }
trap cleanup EXIT

echo "=== sage-decisions.yaml integration test (decision recording) ==="
echo ""

# --- Create fixture with sample entries ---
cat > "$FIXTURE_FILE" <<'YAML'
schema_version: 2
append_only: true
max_entries: 100
entries:
  - run_id: squad-003-1742652000
    artifact: specs/001-echelon-improvements/spec.md
    challenge_type: logical_inconsistency
    challenge_summary: "FR-03 contradicts boundary B-02 regarding external API access."
    outcome: blocked
    resolution: "WHAT agent revised FR-03 to respect boundary B-02 scope."
    was_correct: true
  - run_id: squad-004-1742738400
    artifact: specs/002-rts-bls/spec.md
    challenge_type: quality_threshold
    challenge_summary: "Testability score 0.58 below 0.70 threshold."
    outcome: blocked
    resolution: "WHAT agent improved acceptance criteria; re-validation scored 0.74."
    was_correct: true
  - run_id: squad-005-1742824800
    artifact: specs/002-rts-bls/test-strategy.md
    challenge_type: missing_evidence
    challenge_summary: "No evidence for claimed 99.9% uptime SLA feasibility."
    outcome: passed_with_warnings
    resolution: "Proceeded with warning; SCIENTIST to investigate in next cycle."
    was_correct: false
  - run_id: squad-006-1742911200
    artifact: specs/003-qa-strategy/spec.md
    challenge_type: assumption_violation
    challenge_summary: "Assumption A-05 (all teams use Git) violated by ops team using SVN."
    outcome: blocked
    resolution: "DISCOVER updated assumption A-05; spec revised to support both VCS."
    was_correct: true
  - run_id: squad-007-1742997600
    artifact: specs/003-qa-strategy/boundaries.md
    challenge_type: specification_gap
    challenge_summary: "No NFR for data retention policy despite GDPR references."
    outcome: passed_with_warnings
    resolution: "Added as backlog item; not blocking for V1 scope."
    was_correct: true
YAML

pass "Fixture file created with 5 sample entries"

# --- Validate top-level schema ---
if grep -q '^schema_version: 2' "$FIXTURE_FILE"; then
  pass "schema_version is 2"
else
  fail "schema_version must be 2"
fi

if grep -q '^append_only: true' "$FIXTURE_FILE"; then
  pass "append_only is true"
else
  fail "append_only must be true"
fi

if grep -q '^max_entries: 100' "$FIXTURE_FILE"; then
  pass "max_entries is 100"
else
  fail "max_entries must be 100"
fi

# --- Validate required fields on every entry ---
REQUIRED_FIELDS="run_id artifact challenge_type challenge_summary outcome resolution was_correct"
VALID_CHALLENGE_TYPES="logical_inconsistency missing_evidence assumption_violation quality_threshold specification_gap"
VALID_OUTCOMES="blocked passed_with_warnings passed"

# Count entries
ENTRY_COUNT=$(grep -c '^ *- run_id:' "$FIXTURE_FILE")
if [[ "$ENTRY_COUNT" -eq 5 ]]; then
  pass "Fixture contains exactly 5 entries"
else
  fail "Expected 5 entries, found $ENTRY_COUNT"
fi

# Check each required field is present in every entry
for field in $REQUIRED_FIELDS; do
  COUNT=$(grep -c "[- ] *${field}:" "$FIXTURE_FILE" || true)
  if [[ "$COUNT" -eq "$ENTRY_COUNT" ]]; then
    pass "All entries have required field: $field"
  else
    fail "Field '$field' found $COUNT times, expected $ENTRY_COUNT"
  fi
done

# Validate challenge_type enum values
echo ""
echo "--- Enum validation ---"
INVALID_TYPES=0
while IFS= read -r line; do
  TYPE_VAL=$(echo "$line" | sed 's/.*challenge_type: *//' | tr -d '"' | tr -d "'")
  if ! echo "$VALID_CHALLENGE_TYPES" | grep -qw "$TYPE_VAL"; then
    fail "Invalid challenge_type: $TYPE_VAL"
    ((INVALID_TYPES++))
  fi
done < <(grep 'challenge_type:' "$FIXTURE_FILE")
if [[ "$INVALID_TYPES" -eq 0 ]]; then
  pass "All challenge_type values are valid enums"
fi

# Validate outcome enum values
INVALID_OUTCOMES=0
while IFS= read -r line; do
  OUT_VAL=$(echo "$line" | sed 's/.*outcome: *//' | tr -d '"' | tr -d "'")
  if ! echo "$VALID_OUTCOMES" | grep -qw "$OUT_VAL"; then
    fail "Invalid outcome: $OUT_VAL"
    ((INVALID_OUTCOMES++))
  fi
done < <(grep '^ *outcome:' "$FIXTURE_FILE")
if [[ "$INVALID_OUTCOMES" -eq 0 ]]; then
  pass "All outcome values are valid enums"
fi

# Validate was_correct is boolean
INVALID_BOOL=0
while IFS= read -r line; do
  BOOL_VAL=$(echo "$line" | sed 's/.*was_correct: *//' | tr -d '"' | tr -d "'")
  if [[ "$BOOL_VAL" != "true" && "$BOOL_VAL" != "false" ]]; then
    fail "Invalid was_correct value: $BOOL_VAL (must be true or false)"
    ((INVALID_BOOL++))
  fi
done < <(grep 'was_correct:' "$FIXTURE_FILE")
if [[ "$INVALID_BOOL" -eq 0 ]]; then
  pass "All was_correct values are valid booleans"
fi

# --- Validate self-calibration can compute false-positive rate ---
echo ""
echo "--- Self-calibration computation ---"
OVERTURNED=$(grep 'was_correct: false' "$FIXTURE_FILE" | wc -l | tr -d ' ')
TOTAL=$ENTRY_COUNT
FP_RATE=$((OVERTURNED * 100 / TOTAL))
echo "  Overturned decisions: $OVERTURNED / $TOTAL (${FP_RATE}%)"
if [[ "$OVERTURNED" -eq 1 ]]; then
  pass "Fixture has exactly 1 overturned decision (was_correct: false)"
else
  fail "Expected 1 overturned decision, found $OVERTURNED"
fi
if [[ "$FP_RATE" -eq 20 ]]; then
  pass "False-positive rate is 20% (within acceptable range)"
else
  fail "Expected 20% false-positive rate, got ${FP_RATE}%"
fi

# --- Validate unique challenge_types are covered ---
echo ""
echo "--- Coverage check ---"
UNIQUE_TYPES=$(grep 'challenge_type:' "$FIXTURE_FILE" | sed 's/.*challenge_type: *//' | tr -d '"' | tr -d "'" | sort -u | wc -l | tr -d ' ')
if [[ "$UNIQUE_TYPES" -eq 5 ]]; then
  pass "All 5 challenge_type enum values are represented in fixture"
else
  fail "Expected all 5 challenge_types covered, found $UNIQUE_TYPES unique types"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
