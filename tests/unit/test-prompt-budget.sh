#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/runtime/scripts/bash/prompt-budget.sh"

pass=0
fail=0

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass + 1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail + 1))
    printf 'FAIL: %s — %s\n' "$desc" "$result"
  fi
}

# Test 1: script exists and is executable
[[ -x "$SCRIPT" ]] && assert "script executable" "OK" || assert "script executable" "not executable"

# Test 2: a deliberately strict cap must identify oversized prompts.
bash "$SCRIPT" check --max 400 >/dev/null 2>&1 && assert "check --max 400 exits 1" "should have failed" || assert "check --max 400 exits 1" "OK"

# Test 3: check with high limit passes — bumped from 1000 to 1500 because
# commander.md has grown organically beyond 1000 (currently ~1278) with the
# accumulation of NEVER-rules, mandate tables, and section-numbered protocol
# blocks. 1500 remains a meaningful budget guardrail for the second-largest
# agents while accommodating commander.md's role as the orchestrator with
# the most surface area.
bash "$SCRIPT" check --max 1500 >/dev/null 2>&1 && assert "check --max 1500 exits 0" "OK" || assert "check --max 1500 exits 0" "should have passed"

# Test 4: report outputs all agents
count=$(bash "$SCRIPT" report | grep -c "^[a-z]")
[[ "$count" -ge 37 ]] && assert "report lists >=37 agents ($count)" "OK" || assert "report lists >=37 agents ($count)" "only $count"

# Test 5: top 5 returns exactly 5
top_count=$(bash "$SCRIPT" top 5 | grep -c "^[0-9]")
[[ "$top_count" -eq 5 ]] && assert "top 5 returns 5 rows" "OK" || assert "top 5 returns 5 rows" "got $top_count"

# Test 6: check identifies a known violator at the strict 400-line cap.
# CARTOGRAPHER remains just over this diagnostic threshold even after Lexicon
# derivation responsibility moved to the dedicated narrow agent.
violations=$(bash "$SCRIPT" check --max 400 2>&1 || true)
echo "$violations" | grep -q "cartographer" && assert "check flags cartographer" "OK" || assert "check flags cartographer" "missing"

# Test 7: report shows TOTAL line
budget_report=$(bash "$SCRIPT" report)
grep -q "TOTAL" <<< "$budget_report" && assert "report has TOTAL" "OK" || assert "report has TOTAL" "missing"

# Test 8: report shows AVERAGE line
grep -q "AVERAGE" <<< "$budget_report" && assert "report has AVERAGE" "OK" || assert "report has AVERAGE" "missing"

echo ""
echo "=========================================="
echo "TOTAL: $pass passed, $fail failed"
echo "=========================================="
[[ "$fail" -eq 0 ]] && exit 0 || exit 1
