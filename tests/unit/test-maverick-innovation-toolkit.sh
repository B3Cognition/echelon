#!/usr/bin/env bash
# T-36: Unit test — verify maverick.md contains TRIZ, Design Thinking, First Principles sections

set -euo pipefail

MAVERICK_MD="$(dirname "$0")/../../prosaic/subagents/echelon.maverick.md"
PASS=0
FAIL=0

assert_contains() {
  local label="$1"
  local pattern="$2"
  if grep -qiE "$pattern" "$MAVERICK_MD"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — pattern not found: $pattern"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Unit Test: MAVERICK Innovation Toolkit ==="
echo ""

# Check the toolkit section exists
assert_contains "Innovation Toolkit section exists" \
  "^## Innovation Toolkit"

# --- TRIZ Contradiction Matrix ---
echo ""
echo "--- TRIZ Contradiction Matrix ---"
assert_contains "TRIZ toolkit section" \
  "Toolkit.*TRIZ Contradiction Matrix"
assert_contains "TRIZ 16 software-adapted parameters" \
  "TRIZ Software-Adapted Parameters"
assert_contains "TRIZ parameter table" \
  "Speed of operation|Response time.*throughput"
assert_contains "Reliability parameter" \
  "Reliability.*Uptime.*fault tolerance"
assert_contains "TRIZ structured output format" \
  "TRIZ.*Structured Output Format|TRIZ Analysis:"
assert_contains "Technical contradiction template" \
  "Technical Contradiction"
assert_contains "Physical contradiction template" \
  "Physical Contradiction"
assert_contains "Matrix lookup instruction" \
  "Matrix Lookup"
assert_contains "Principle application table" \
  "Principle Application"
assert_contains "Resolution quality assessment" \
  "RESOLVES.*COMPROMISES"

# --- Design Thinking 5-Phase ---
echo ""
echo "--- Design Thinking 5-Phase Structure ---"
assert_contains "Design Thinking toolkit section" \
  "Toolkit.*Design Thinking 5-Phase"
assert_contains "Phase 1: Empathize" \
  "Phase 1.*Empathize"
assert_contains "Phase 2: Define" \
  "Phase 2.*Define"
assert_contains "Phase 3: Ideate" \
  "Phase 3.*Ideate"
assert_contains "Phase 4: Prototype" \
  "Phase 4.*Prototype"
assert_contains "Phase 5: Test" \
  "Phase 5.*Test"
assert_contains "How Might We reframing" \
  "How [Mm]ight [Ww]e"
assert_contains "Design Thinking structured output format" \
  "Design Thinking.*Structured Output Format|Design Thinking Analysis:"
assert_contains "Empathy sources" \
  "Empathy sources|empathy"
assert_contains "Cheapest experiment" \
  "Cheapest experiment|cheapest"

# --- First Principles Decomposition ---
echo ""
echo "--- First Principles Decomposition ---"
assert_contains "First Principles toolkit section" \
  "Toolkit.*First Principles Decomposition"
assert_contains "Assumption chain identification" \
  "assumption chain"
assert_contains "Ground truths definition" \
  "ground truth|Ground Truths"
assert_contains "Convention vs fundamental distinction" \
  "CONVENTION.*FUNDAMENTAL|convention.*fundamental"
assert_contains "First Principles structured output format" \
  "First Principles.*Structured Output Format|First Principles Decomposition:"
assert_contains "Rebuild from ground truths" \
  "[Rr]ebuild from ground"
assert_contains "Ground-Truth Solution section" \
  "Ground-Truth Solution"
assert_contains "Recommendation category ADOPT" \
  "ADOPT:"
assert_contains "Recommendation category INVESTIGATE" \
  "INVESTIGATE:"
assert_contains "Recommendation category KEEP" \
  "KEEP:"

# --- General Toolkit Properties ---
echo ""
echo "--- General Properties ---"
assert_contains "When to use criteria for TRIZ" \
  "When to use.*contradiction"
assert_contains "When to use criteria for Design Thinking" \
  "When to use.*wrong problem|problem reframing"
assert_contains "When to use criteria for First Principles" \
  "When to use.*incremental|rethinking fundamentals"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
