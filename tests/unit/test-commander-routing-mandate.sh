#!/usr/bin/env bash
# Unit tests for COMMANDER routing_decision mandate and quality_scores provenance
# Tests: CMD-01, CMD-02, CMD-03 per test-strategy.md
# Run: bash tests/unit/test-commander-routing-mandate.sh
#
# After commit 448da9b "slim commander.md — harness owns loop/routing/state":
#   - routing_decision journal schema (from_phase, to_phase, reason, evoi_score)
#     moved to extension/workflow/journal-entry-types.yaml
#   - quality_scores WHY1 prohibition stays in commander.md (Rule 8) but with
#     broader wording: "NEVER write quality_scores[] entries in your own outputs"
#   - pass_counter normalization lives in src/kernel/accessors.py (FR-007/FR-013)
#   - understanding-validate reference lives in extension/workflow/phases/phase1-why2.md

set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMANDER_MD="$ROOT_DIR/extension/agents/control/commander.md"
JOURNAL_TYPES="$ROOT_DIR/extension/workflow/journal-entry-types.yaml"
WHY2_PHASE="$ROOT_DIR/extension/workflow/phases/phase1-why2.md"
ACCESSORS_PY="$ROOT_DIR/src/kernel/accessors.py"

PASS=0
FAIL=0

assert_grep() {
  local label="$1" pattern="$2" file="$3"
  if grep -qi "$pattern" "$file"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (pattern not found in $(basename "$file"): $pattern)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== CMD-01: routing_decision schema present in journal-entry-types.yaml ==="
# After 448da9b, the routing_decision journal schema moved from commander.md
# to the canonical type registry at extension/workflow/journal-entry-types.yaml.
assert_grep "CMD-01 routing_decision entry" "routing_decision" "$JOURNAL_TYPES"
assert_grep "CMD-01 mentions from_phase" "from_phase" "$JOURNAL_TYPES"
assert_grep "CMD-01 mentions evoi_score" "evoi_score" "$JOURNAL_TYPES"

echo ""
echo "=== CMD-02: routing_decision required fields in journal-entry-types.yaml ==="
# The required_data_fields line lists all four mandatory fields on one line.
assert_grep "CMD-02 from_phase in required_data_fields" "required_data_fields.*from_phase\|from_phase.*to_phase" "$JOURNAL_TYPES"
assert_grep "CMD-02 to_phase in required_data_fields" "required_data_fields.*to_phase\|from_phase.*to_phase" "$JOURNAL_TYPES"
assert_grep "CMD-02 reason in required_data_fields" "required_data_fields.*reason\|from_phase.*reason" "$JOURNAL_TYPES"
assert_grep "CMD-02 evoi_score in required_data_fields" "required_data_fields.*evoi_score\|reason.*evoi_score" "$JOURNAL_TYPES"

echo ""
echo "=== CMD-03: WHY1/quality_scores prohibition and pass_counter provenance ==="
# WHY1 prohibition (Rule 8): COMMANDER must not write quality_scores[] —
# now a paired ALWAYS/NEVER rule in commander.md (lines 46-47 after slimming).
assert_grep "CMD-03 quality_scores NEVER rule in commander.md" "NEVER write.*quality_scores" "$COMMANDER_MD"
# understanding-validate reference: lives in phase1-why2.md (the phase that runs Understanding)
assert_grep "CMD-03 understanding-validate in why2 phase" "understanding.validate\|understanding-validate" "$WHY2_PHASE"
# pass_counter normalization: lives in src/kernel/accessors.py (FR-007, FR-013)
assert_grep "CMD-03 pass_counter normalization in accessors.py" "pass_counter" "$ACCESSORS_PY"

echo ""
echo "═══════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
