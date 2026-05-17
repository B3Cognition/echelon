#!/usr/bin/env bash
# Unit tests for COMMANDER routing_decision mandate and quality_scores provenance
# Tests: CMD-01, CMD-02, CMD-03 per test-strategy.md
# Run: bash tests/unit/test-commander-routing-mandate.sh

set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMANDER_MD="$ROOT_DIR/extension/agents/control/commander.md"

PASS=0
FAIL=0

assert_grep() {
  local label="$1" pattern="$2"
  if grep -qi "$pattern" "$COMMANDER_MD"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (pattern not found: $pattern)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== CMD-01: NEVER-rule about routing_decision present ==="
assert_grep "CMD-01 NEVER-rule text" "NEVER write a.*routing_decision.*without"
assert_grep "CMD-01 mentions from_phase" "from_phase"
assert_grep "CMD-01 mentions evoi_score" "evoi_score"

echo ""
echo "=== CMD-02: routing_decision field mandate documented ==="
assert_grep "CMD-02 from_phase in mandate" "from_phase.*phase node"
assert_grep "CMD-02 to_phase in mandate" "to_phase.*phase node"
assert_grep "CMD-02 reason in mandate" "reason.*justification\|reason.*Prose"
assert_grep "CMD-02 evoi_score in mandate" "evoi_score.*number\|evoi_score.*not_computed"

echo ""
echo "=== CMD-03: WHY1 prohibition documented ==="
assert_grep "CMD-03 WHY1 prohibition" "NEVER write.*quality_scores.*WHY1\|NEVER write.*quality_scores.*phase1-why1"
assert_grep "CMD-03 source enum values" "tool:understanding.validate"
assert_grep "CMD-03 pass_counter directive" "pass_counter.*not.*pass\|pass_counter.*field name"

echo ""
echo "═══════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
