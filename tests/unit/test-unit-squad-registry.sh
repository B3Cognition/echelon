#!/usr/bin/env bash
# test-unit-squad-registry.sh — structural validation for squad harness
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0; FAIL=0

assert_eq() {
    if [ "$1" = "$2" ]; then
        echo "PASS: $3"
        PASS=$((PASS+1))
    else
        echo "FAIL: $3 (expected '$2', got '$1')"
        FAIL=$((FAIL+1))
    fi
}

assert_le() {
    if [ "$1" -le "$2" ]; then
        echo "PASS: $3"
        PASS=$((PASS+1))
    else
        echo "FAIL: $3 (expected ≤$2 lines, got $1)"
        FAIL=$((FAIL+1))
    fi
}

# 1. echelon.run.md is ≤ 100 lines
RUNMD_LINES=$(wc -l < "$ROOT/extension/commands/echelon.run.md")
assert_le "$RUNMD_LINES" 100 "echelon.run.md ≤ 100 lines"

# 2. commander.md is ≤ 250 lines (was ~1200 before slimming)
CMD_LINES=$(wc -l < "$ROOT/extension/agents/control/commander.md")
assert_le "$CMD_LINES" 250 "commander.md ≤ 250 lines"

# 3. All phase types in definition.yaml have a registered executor
TYPES=$(python3 -c "
import yaml, sys
sys.path.insert(0, '$ROOT/src')
d = yaml.safe_load(open('$ROOT/extension/workflow/definition.yaml'))
types = {p.get('type','agent') for p in d.get('phases',[])}
print(' '.join(sorted(types)))
" 2>/dev/null || echo "ERROR")

if [ "$TYPES" = "ERROR" ]; then
    echo "FAIL: could not parse definition.yaml phase types"
    FAIL=$((FAIL+1))
else
    EXECUTORS="agent commander_internal conditional_sequential human_gate staged_parallel terminal"
    for t in $TYPES; do
        if echo "$EXECUTORS" | grep -qw "$t"; then
            echo "PASS: executor registered for type '$t'"
            PASS=$((PASS+1))
        else
            echo "FAIL: no executor for type '$t'"
            FAIL=$((FAIL+1))
        fi
    done
fi

# 4. All new harness modules importable
~/.echelon/venv/bin/python -c "
import sys
sys.path.insert(0, '$ROOT/src')
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.condition_evaluator import ConditionEvaluator
from harness.phase_graph import PhaseGraph
from harness.squad_state import SquadStateStore
from harness.squad_executors import AgentExecutor, StagedParallelExecutor
from harness.squad import SquadController
print('all modules importable')
" && echo "PASS: all squad harness modules importable" && PASS=$((PASS+1)) || { echo "FAIL: module import failed"; FAIL=$((FAIL+1)); }

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
