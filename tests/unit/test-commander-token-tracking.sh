#!/usr/bin/env bash
# T-25: Unit test — verify commander.md contains token tracking requirements
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMMANDER="$ROOT/agents/control/commander.md"
FAILURES=0

assert_grep() {
  local pattern="$1"
  local description="$2"
  if grep -q "$pattern" "$COMMANDER"; then
    echo "PASS: $description"
  else
    echo "FAIL: $description (pattern: $pattern)"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "=== Commander Token Tracking Unit Tests ==="
echo ""

# Token ledger structure
assert_grep "token_ledger" "commander.md references token_ledger"
assert_grep "dispatch_id" "commander.md defines dispatch_id field"
assert_grep "agent_codename" "commander.md defines agent_codename field"
assert_grep "estimated_tokens" "commander.md defines estimated_tokens field"
assert_grep "per_agent" "commander.md tracks per-agent token totals"
assert_grep "per_phase" "commander.md tracks per-phase token totals"
assert_grep "total_estimated_tokens" "commander.md tracks cumulative total"

# Budget check before dispatch
assert_grep "Budget Check Before Dispatch" "commander.md has budget check section"
assert_grep "analysis.token_budget_k" "commander.md references correct budget config key"
# Negative assertion: old broken key must not appear
if grep -q "budget\.total_tokens" "$COMMANDER"; then
  echo "FAIL: commander.md still references non-existent budget.total_tokens key"
  FAILURES=$((FAILURES + 1))
else
  echo "PASS: commander.md does not reference non-existent budget.total_tokens key"
fi
assert_grep "BUDGET_EXHAUSTED" "commander.md defines budget exhausted signal"

# Dispatch logging
assert_grep "Dispatch Logging" "commander.md has dispatch logging section"
assert_grep "dispatch_id.*D-" "commander.md defines dispatch_id format"
assert_grep "total_dispatches" "commander.md tracks dispatch count"

# Per-tier enforcement
assert_grep "Per-Tier Budget Enforcement" "commander.md has per-tier enforcement"

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL TESTS PASSED ($(grep -c 'PASS:' <<< "$(grep -c '' /dev/null || true)"))"
  echo "RESULT: PASS"
else
  echo "FAILURES: $FAILURES"
  echo "RESULT: FAIL"
  exit 1
fi
