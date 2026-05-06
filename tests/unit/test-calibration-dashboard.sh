#!/usr/bin/env bash
# T-34: Unit test — verify auditor.md contains calibration dashboard generation sections

set -euo pipefail

AUDITOR_MD="$(dirname "$0")/../../extension/agents/learning/auditor.md"
PASS=0
FAIL=0

assert_contains() {
  local label="$1"
  local pattern="$2"
  if grep -qiE "$pattern" "$AUDITOR_MD"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — pattern not found: $pattern"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Unit Test: AUDITOR Calibration Dashboard Generation ==="
echo ""

# Check the section exists
assert_contains "Calibration Dashboard Generation section exists" \
  "^## Calibration Dashboard Generation"

# Check all 5 dashboard sections
echo ""
echo "--- Dashboard Sections ---"
assert_contains "Section 1: Domain Calibration Overview" \
  "Domain Calibration Overview"
# Sections 2-3 moved to INTERNALIZER after P1 split — check internalizer.md
INTERNALIZER_MD="$(dirname "$0")/../../extension/agents/learning/internalizer.md"
if grep -qiE "Agent Internalization Health|internalization.*health|per-agent.*scoring" "$INTERNALIZER_MD" 2>/dev/null; then
  echo "  PASS: Section 2: Agent Internalization Health (in internalizer.md)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: Section 2: Agent Internalization Health — not in internalizer.md"
  FAIL=$((FAIL + 1))
fi
if grep -qiE "Cross-Validation|CV-1|CV-2|CV-3" "$INTERNALIZER_MD" 2>/dev/null; then
  echo "  PASS: Section 3: Cross-Validation Flags Summary (in internalizer.md)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: Section 3: Cross-Validation Flags — not in internalizer.md"
  FAIL=$((FAIL + 1))
fi
assert_contains "Section 4: Evolution Signals Status" \
  "Evolution Signals"
assert_contains "Section 5: Calibration Health Score" \
  "Calibration Health Score"

# Check health score computation
echo ""
echo "--- Health Score ---"
assert_contains "Health score formula" \
  "calibration_health.*=.*domains_above_threshold|calibration_health"
assert_contains "HEALTHY threshold" \
  "HEALTHY.*0\.75|>= 0\.75"
assert_contains "DEGRADED threshold" \
  "DEGRADED.*0\.50|0\.50.*0\.74"
assert_contains "CRITICAL threshold" \
  "CRITICAL.*< 0\.50|CRITICAL.*0\.50"

# Check when to generate
echo ""
echo "--- Generation Trigger ---"
assert_contains "Generated during FINALIZE" \
  "FINALIZE"
assert_contains "COMMANDER requests dashboard" \
  "COMMANDER.*request|COMMANDER.*dashboard"

# Check output path
assert_contains "Output path defined" \
  "calibration-dashboard\.md"

# Check risk levels
echo ""
echo "--- Risk Level Definitions ---"
assert_contains "HIGH risk definition" \
  "HIGH.*accuracy.*< 0\.5|HIGH.*< 0\.5"
assert_contains "MEDIUM risk definition" \
  "MEDIUM.*0\.5.*0\.75"
assert_contains "LOW risk definition" \
  "LOW.*> 0\.75|LOW.*0\.75"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
