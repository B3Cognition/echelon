#!/usr/bin/env bash
# T-32: Unit test — verify internalization scoring is documented with all 4
#        categories (Absorption, Accuracy, Calibration, Transfer).
#
# Post-split history (see tests/unit/test-auditor-internalizer-split.sh): the
# internalization computation was extracted from auditor.md into
# internalizer.md when INTERNALIZER became its own agent. The "Per-Agent
# Internalization Scoring" section, category definitions, composite/trend
# rules, storage format, and null/cap rules all moved with it. This test
# verifies the documentation still exists; the target file just moved.

set -euo pipefail

TARGET_MD="$(dirname "$0")/../../extension/agents/learning/internalizer.md"
PASS=0
FAIL=0

assert_contains() {
  local label="$1"
  local pattern="$2"
  if grep -qiE "$pattern" "$TARGET_MD"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — pattern not found: $pattern"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Unit Test: AUDITOR Per-Agent Internalization Scoring ==="
echo ""

# Check the section exists
assert_contains "Per-Agent Internalization Scoring section exists" \
  "^## Per-Agent Internalization Scoring"

# Check all 4 categories are defined
echo ""
echo "--- Category Definitions ---"
assert_contains "Absorption category (I-01 to I-04)" \
  "Absorption.*I-01.*I-04|Absorption.*requirement_coverage.*dependency_awareness"
assert_contains "Accuracy category (I-05 to I-08)" \
  "Accuracy.*I-05.*I-08|Accuracy.*numeric_contradiction.*keyword_scope"
assert_contains "Calibration category (I-09 to I-12)" \
  "Calibration.*I-09.*I-12|Calibration.*confidence_accuracy.*escalation_precision"
assert_contains "Transfer category (I-13 to I-16)" \
  "Transfer.*I-13.*I-16|Transfer.*first_pass_acceptance.*priority_alignment"

# Check composite score computation
echo ""
echo "--- Composite Score ---"
assert_contains "Composite score computation" \
  "composite.score|composite_score"
assert_contains "Category weights defined" \
  "weight.*0\.(20|30)|Absorption weight.*0\.30"

# Check trend computation
echo ""
echo "--- Trend Analysis ---"
assert_contains "Trend improving definition" \
  "improving.*composite.*mean"
assert_contains "Trend declining definition" \
  "declining.*composite.*mean"
assert_contains "Trend stable definition" \
  "stable.*within"
assert_contains "Insufficient data handling" \
  "insufficient_data|insufficient.data"

# Check storage format
echo ""
echo "--- Storage Format ---"
assert_contains "agent-scores.yaml storage" \
  "agent-scores\.yaml"
assert_contains "internalization sub-object" \
  "internalization:"
assert_contains "category_scores block" \
  "category_scores:"
assert_contains "metric_values block" \
  "metric_values:"
assert_contains "History array" \
  "history:"

# Check null handling rules
echo ""
echo "--- Rules ---"
assert_contains "Null vs zero rule" \
  "null.*not.*0\.0|null.*not 0"
assert_contains "History cap" \
  "capped at 20|oldest removed"
assert_contains "KB write protocol" \
  "kb-write\.sh"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
