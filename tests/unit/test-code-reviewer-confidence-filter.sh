#!/usr/bin/env bash
# T-07: Unit test — verify code-reviewer.md contains confidence filtering rules
# Greps the prompt file for required sections and patterns.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET="$REPO_ROOT/extension/agents/build/code-reviewer.md"

PASS=0
FAIL=0

assert_grep() {
  local label="$1"
  local pattern="$2"
  if grep -qiE "$pattern" "$TARGET"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (pattern: $pattern)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== CODE REVIEWER Confidence Filter Unit Tests ==="
echo "Target: $TARGET"
echo ""

# --- 80% threshold ---
echo "[1] Confidence threshold (80%)"
assert_grep "80% threshold mentioned" ">80%|80.*confidence|confidence.*80"
assert_grep "confidence_threshold config key" "confidence_threshold"
assert_grep "default 80" "default.*80|default:.*80"

# --- Consolidation rules ---
echo ""
echo "[2] Consolidation rules"
assert_grep "consolidation section exists" "consolidation rules"
assert_grep "group similar issues" "group similar issues"
assert_grep "consolidated example" "5 functions missing error handling"
assert_grep "consolidation criteria" "same category.*same severity|same severity.*same root cause"

# --- Severity-based verdict mapping ---
echo ""
echo "[3] Severity-based verdict mapping"
assert_grep "APPROVED verdict condition" "no critical.*high.*approved|approved.*no critical"
assert_grep "CHANGES_REQUESTED verdict condition" "high.*changes_requested|changes_requested.*high"
assert_grep "BLOCKED verdict condition" "critical.*blocked|blocked.*critical"
assert_grep "BLOCKED triggers: security" "security"
assert_grep "BLOCKED triggers: data loss" "data loss"
assert_grep "BLOCKED triggers: spec violation" "spec violation"

# --- Stylistic suppression ---
echo ""
echo "[4] Stylistic suppression"
assert_grep "suppress stylistic preferences" "suppress stylistic preferences"
assert_grep "unless violate ADR" "violate.*adr|adr.*violat"

# --- Finding format fields ---
echo ""
echo "[5] Finding format fields"
assert_grep "confidence field" "confidence.*percentage|confidence.*0.*100"
assert_grep "severity field" "critical.*high.*medium"
assert_grep "file_line field" "file_line|file.*line.*number"
assert_grep "suggested_fix field" "suggested_fix"

# --- Summary table ---
echo ""
echo "[6] Summary table format"
assert_grep "summary table section" "summary table"
assert_grep "severity count status columns" "severity.*count.*status"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "All checks passed."
