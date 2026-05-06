#!/usr/bin/env bash
# Unit test: verify SENTINEL prompt contains all 5 Flakiness Management subsections
set -euo pipefail

SENTINEL="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)/extension/agents/solution/sentinel.md"
PASS=0
FAIL=0

check() {
  local label="$1" pattern="$2"
  if grep -q "$pattern" "$SENTINEL"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label — pattern not found: $pattern"
    FAIL=$((FAIL + 1))
  fi
}

check "Flakiness Management heading" "Flakiness Management"
check "Detection Protocol"           "Detection Protocol"
check "Quarantine Process"           "Quarantine Process"
check "Root Cause Taxonomy"          "Root Cause Taxonomy"
check "Stability Targets"            "Stability Targets"
check "Review Cadence"               "Review Cadence"

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
