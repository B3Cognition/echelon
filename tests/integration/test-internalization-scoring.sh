#!/usr/bin/env bash
# T-32: Integration test — fixture agent-scores with internalization data, validate schema

set -euo pipefail

FIXTURES_DIR="$(dirname "$0")/../fixtures/internalization"
FIXTURE_FILE="$FIXTURES_DIR/agent-scores-internalization.yaml"
PASS=0
FAIL=0

assert_true() {
  local label="$1"
  local result="$2"
  if [ "$result" = "true" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    FAIL=$((FAIL + 1))
  fi
}

# --- Step 1: Create fixture file ---
echo "=== Integration Test: Internalization Scoring Schema ==="
echo ""
echo "--- Creating fixture ---"

cat > "$FIXTURE_FILE" << 'YAML'
schema_version: 1

agents:
  ARCHITECT:
    lifetime_score: 42
    current_run_score: 12
    badges: []
    internalization:
      composite_score: 0.88
      category_scores:
        absorption: 0.91
        accuracy: 0.85
        calibration: 0.87
        transfer: 0.82
      metric_values:
        I_01_requirement_coverage_rate: 0.93
        I_02_constraint_adherence_score: 0.89
        I_03_terminology_fidelity: 0.91
        I_04_dependency_awareness: 0.90
        I_05_numeric_contradiction_rate: 0.88
        I_06_uncited_decision_rate: 0.84
        I_07_cross_reference_accuracy: 0.86
        I_08_keyword_scope_rate: 0.82
        I_09_confidence_accuracy: 0.89
        I_10_doubt_signal_quality: 0.85
        I_11_blind_spot_rate: 0.87
        I_12_escalation_precision: 0.86
        I_13_first_pass_acceptance: 0.80
        I_14_rework_severity: 0.85
        I_15_explicit_decision_traceability: 0.82
        I_16_priority_alignment: 0.81
      trend: "improving"
      run_id: "squad-010-1742652000"
      cold_start_phase: 3
      history:
        - run_id: "squad-009"
          composite_score: 0.85
          timestamp: "2026-03-22T10:00:00Z"
        - run_id: "squad-008"
          composite_score: 0.83
          timestamp: "2026-03-21T10:00:00Z"
    history: []

  IMPLEMENTER:
    lifetime_score: 18
    current_run_score: 5
    badges: []
    internalization:
      composite_score: 0.62
      category_scores:
        absorption: 0.70
        accuracy: 0.58
        calibration: null
        transfer: null
      metric_values:
        I_01_requirement_coverage_rate: 0.75
        I_02_constraint_adherence_score: 0.68
        I_03_terminology_fidelity: 0.72
        I_04_dependency_awareness: 0.65
        I_05_numeric_contradiction_rate: 0.60
        I_06_uncited_decision_rate: 0.55
        I_07_cross_reference_accuracy: 0.58
        I_08_keyword_scope_rate: 0.59
        I_09_confidence_accuracy: null
        I_10_doubt_signal_quality: null
        I_11_blind_spot_rate: null
        I_12_escalation_precision: null
        I_13_first_pass_acceptance: null
        I_14_rework_severity: null
        I_15_explicit_decision_traceability: null
        I_16_priority_alignment: null
      trend: "declining"
      run_id: "squad-010-1742652000"
      cold_start_phase: 1
      history:
        - run_id: "squad-009"
          composite_score: 0.66
          timestamp: "2026-03-22T10:00:00Z"
    history: []

  SCOUT:
    lifetime_score: 10
    current_run_score: 3
    badges: []
    internalization:
      composite_score: null
      category_scores:
        absorption: null
        accuracy: null
        calibration: null
        transfer: null
      metric_values:
        I_01_requirement_coverage_rate: null
        I_02_constraint_adherence_score: null
        I_03_terminology_fidelity: null
        I_04_dependency_awareness: null
        I_05_numeric_contradiction_rate: null
        I_06_uncited_decision_rate: null
        I_07_cross_reference_accuracy: null
        I_08_keyword_scope_rate: null
        I_09_confidence_accuracy: null
        I_10_doubt_signal_quality: null
        I_11_blind_spot_rate: null
        I_12_escalation_precision: null
        I_13_first_pass_acceptance: null
        I_14_rework_severity: null
        I_15_explicit_decision_traceability: null
        I_16_priority_alignment: null
      trend: "insufficient_data"
      run_id: "squad-010-1742652000"
      cold_start_phase: 1
      history: []
    history: []
YAML

echo "  Fixture written to: $FIXTURE_FILE"

# --- Step 2: Validate schema structure ---
echo ""
echo "--- Validating schema ---"

# Check top-level structure
assert_true "schema_version field exists" \
  "$(grep -q 'schema_version:' "$FIXTURE_FILE" && echo true || echo false)"

assert_true "agents section exists" \
  "$(grep -q '^agents:' "$FIXTURE_FILE" && echo true || echo false)"

# Check ARCHITECT has full internalization sub-object
assert_true "ARCHITECT has internalization sub-object" \
  "$(awk '/ARCHITECT:/,/^$/' "$FIXTURE_FILE" | grep -q 'internalization:' && echo true || echo false)"

assert_true "composite_score is a float" \
  "$(grep 'composite_score: 0\.' "$FIXTURE_FILE" >/dev/null && echo true || echo false)"

# Check all 4 category scores present
assert_true "absorption category present" \
  "$(grep -q 'absorption:' "$FIXTURE_FILE" && echo true || echo false)"

assert_true "accuracy category present" \
  "$(grep -q 'accuracy:' "$FIXTURE_FILE" && echo true || echo false)"

assert_true "calibration category present" \
  "$(grep -q 'calibration:' "$FIXTURE_FILE" && echo true || echo false)"

assert_true "transfer category present" \
  "$(grep -q 'transfer:' "$FIXTURE_FILE" && echo true || echo false)"

# Check all 16 metric fields (I_01 through I_16)
echo ""
echo "--- Validating 16 metrics ---"
for i in $(seq -w 1 16); do
  metric="I_${i}_"
  assert_true "Metric $metric present" \
    "$(grep -q "$metric" "$FIXTURE_FILE" && echo true || echo false)"
done

# Check trend values
echo ""
echo "--- Validating trend values ---"
assert_true "improving trend present" \
  "$(grep -q 'trend: \"improving\"' "$FIXTURE_FILE" && echo true || echo false)"

assert_true "declining trend present" \
  "$(grep -q 'trend: \"declining\"' "$FIXTURE_FILE" && echo true || echo false)"

assert_true "insufficient_data trend present" \
  "$(grep -q 'trend: \"insufficient_data\"' "$FIXTURE_FILE" && echo true || echo false)"

# Check null handling
echo ""
echo "--- Validating null handling ---"
assert_true "null values present for cold-start metrics" \
  "$(grep -c ': null' "$FIXTURE_FILE" | awk '{ print ($1 > 0) ? "true" : "false" }')"

assert_true "SCOUT has null composite_score" \
  "$(awk '/SCOUT:/,/history:/' "$FIXTURE_FILE" | grep -q 'composite_score: null' && echo true || echo false)"

# Check cold_start_phase
assert_true "cold_start_phase field present" \
  "$(grep -q 'cold_start_phase:' "$FIXTURE_FILE" && echo true || echo false)"

# Check run_id
assert_true "run_id field present in internalization" \
  "$(grep -q 'run_id: \"squad-010' "$FIXTURE_FILE" && echo true || echo false)"

# Check history sub-array
assert_true "history array has timestamp" \
  "$(grep -q 'timestamp:' "$FIXTURE_FILE" && echo true || echo false)"

# --- Step 3: Validate value ranges ---
echo ""
echo "--- Validating value ranges ---"

# Extract all numeric metric values and check they are in [0.0, 1.0]
out_of_range=$(grep -E 'I_[0-9]+_.*: [0-9]' "$FIXTURE_FILE" | awk -F': ' '{val=$2; if (val+0 < 0.0 || val+0 > 1.0) print $0}')
assert_true "All metric values in [0.0, 1.0]" \
  "$([ -z "$out_of_range" ] && echo true || echo false)"

# Check composite scores are in range
composite_out=$(grep 'composite_score: [0-9]' "$FIXTURE_FILE" | awk -F': ' '{val=$2; if (val+0 < 0.0 || val+0 > 1.0) print $0}')
assert_true "All composite scores in [0.0, 1.0]" \
  "$([ -z "$composite_out" ] && echo true || echo false)"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
