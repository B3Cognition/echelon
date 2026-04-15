#!/usr/bin/env bash
# Integration test: verify SAGE flakiness validation catches presence/absence
# of the 5 Flakiness Management subsections in SENTINEL test-strategy output
set -euo pipefail

FIXTURES_DIR="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)/tests/fixtures/agent-outputs/sentinel"
POSITIVE="$FIXTURES_DIR/test-strategy-with-flakiness.md"
NEGATIVE="$FIXTURES_DIR/test-strategy-without-flakiness.md"

HEADINGS=("Detection Protocol" "Quarantine Process" "Root Cause Taxonomy" "Stability Targets" "Review Cadence")
PASS=0
FAIL=0

echo "=== Positive fixture (should have all 5 subsections) ==="
for h in "${HEADINGS[@]}"; do
  if grep -q "$h" "$POSITIVE"; then
    echo "  PASS: '$h' found"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: '$h' NOT found in positive fixture"
    FAIL=$((FAIL + 1))
  fi
done

echo ""
echo "=== Negative fixture (should be missing all 5 subsections) ==="
for h in "${HEADINGS[@]}"; do
  if grep -q "$h" "$NEGATIVE"; then
    echo "  FAIL: '$h' found in negative fixture (should be absent)"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: '$h' correctly absent"
    PASS=$((PASS + 1))
  fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
