#!/usr/bin/env bash
# T-25: Unit test — verify token tracking requirements exist in their canonical locations
# After commit 448da9b "slim commander.md — harness owns loop/routing/state":
#   - token_ledger schema → src/hormone_calc/observable.py (reads total_estimated_tokens)
#   - token_ledger usage docs → extension/agents/build/progress-tracker.md
#   - dispatch_id field → src/hormone_calc/observable.py
#   - agent_codename field → extension/scripts/token-logger.py
#   - estimated_tokens → extension/agents/build/progress-tracker.md
#   - per_agent stats → extension/scripts/token-logger.py
#   - token_budget_k config key → src/echelon/cli.py (analysis.token_budget_k)
#   - budget_exhausted signal → extension/workflow/journal-entry-types.yaml
#   - per_phase checkpoints → extension/config-template.yml
#   Sections "Budget Check Before Dispatch", "Dispatch Logging", "Per-Tier Budget
#   Enforcement", and "total_dispatches" were removed from commander.md entirely —
#   the harness owns these in src/harness/ralph.py and src/harness/squad.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

OBSERVABLE="$ROOT/src/hormone_calc/observable.py"
PROGRESS_TRACKER="$ROOT/extension/agents/build/progress-tracker.md"
TOKEN_LOGGER="$ROOT/extension/scripts/token-logger.py"
CONFIG_TEMPLATE="$ROOT/extension/config-template.yml"
CLI="$ROOT/src/echelon/cli.py"
JOURNAL_TYPES="$ROOT/extension/workflow/journal-entry-types.yaml"

FAILURES=0

assert_grep() {
  local pattern="$1"
  local description="$2"
  local file="$3"
  if grep -q "$pattern" "$file"; then
    echo "PASS: $description"
  else
    echo "FAIL: $description (pattern: $pattern in $(basename "$file"))"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "=== Token Tracking Unit Tests (canonical locations post-448da9b) ==="
echo ""

# Token ledger structure — now in hormone_calc/observable.py and progress-tracker.md
assert_grep "token_ledger" "token_ledger referenced in observable.py" "$OBSERVABLE"
assert_grep "dispatch_id" "dispatch_id field defined in observable.py" "$OBSERVABLE"
assert_grep "total_estimated_tokens" "total_estimated_tokens tracked in observable.py" "$OBSERVABLE"

# agent_codename — token-logger.py
assert_grep "agent_codename" "agent_codename field in token-logger.py" "$TOKEN_LOGGER"

# estimated_tokens, per_agent tracking — progress-tracker.md + token-logger.py
assert_grep "estimated_tokens" "estimated_tokens in progress-tracker.md" "$PROGRESS_TRACKER"
assert_grep "per_agent" "per-agent stats in token-logger.py" "$TOKEN_LOGGER"

# per_phase checkpoints — config-template.yml
assert_grep "per_phase" "per_phase checkpoint in config-template.yml" "$CONFIG_TEMPLATE"

# token_budget_k config key — src/echelon/cli.py
assert_grep "analysis.token_budget_k\|token_budget_k" "analysis.token_budget_k config key in cli.py" "$CLI"

# Negative assertion: old broken key must not appear in commander.md
COMMANDER="$ROOT/extension/agents/control/commander.md"
if grep -q "budget\.total_tokens" "$COMMANDER"; then
  echo "FAIL: commander.md still references non-existent budget.total_tokens key"
  FAILURES=$((FAILURES + 1))
else
  echo "PASS: commander.md does not reference non-existent budget.total_tokens key"
fi

# budget_exhausted signal — journal-entry-types.yaml (was BUDGET_EXHAUSTED in commander.md;
# now recorded as the lowercase journal entry type "budget_exhausted" per canonical schema)
assert_grep "budget_exhausted" "budget_exhausted signal in journal-entry-types.yaml" "$JOURNAL_TYPES"

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  echo "RESULT: PASS"
else
  echo "FAILURES: $FAILURES"
  echo "RESULT: FAIL"
  exit 1
fi
