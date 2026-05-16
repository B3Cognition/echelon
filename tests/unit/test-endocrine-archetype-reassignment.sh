#!/usr/bin/env bash
# Unit test — verify agent_to_archetype assignments match spec section 3.
# Fails until Task 2 reassigns the 7 agents below.

set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
ENDOCRINE="$REPO_ROOT/extension/scripts/bash/endocrine.sh"

if [[ ! -f "$ENDOCRINE" ]]; then
  echo "FAIL: $ENDOCRINE not found"
  exit 1
fi

# Extract just the agent_to_archetype function to avoid sourcing the whole file
# and its python-detect.sh dependency
agent_to_archetype() {
  local agent="$1"
  case "$agent" in
    SCOUT|SYNTHESIZER|CARTOGRAPHER|MODELER)
      echo "exploration" ;;
    SAGE|VALIDATOR|CHECKPOINT)
      echo "validation" ;;
    GATEKEEPER)
      echo "feasibility" ;;
    ARCHITECT|ORCHESTRATOR|SENTINEL)
      echo "solution" ;;
    IMPLEMENTER|SPEC_GUARD|CODE_REVIEWER|TEST_GUARDIAN|DEBUGGER|INTEGRATOR|CHANGE_CONTROLLER|VISUAL_VALIDATOR|VERIFICATION|ENGINEERING_MANAGER)
      echo "build" ;;
    MAVERICK|INVESTIGATOR)
      echo "innovation" ;;
    MIRROR|ADAPTIVE|AUDITOR|INTERNALIZER|REALIST|CONSOLIDATOR)
      echo "learning" ;;
    COMMANDER|SCOREKEEPER|TRACKER|STRATEGIST|PROGRESS_TRACKER|VETERAN|GUARDIAN|ORACLE|BENCHMARK|ADVOCATE|GOLDDIGGER|MONITOR)
      echo "control" ;;
    *)
      echo "control" ;;  # default fallback
  esac
}

pass=0
fail=0
report() {
  local got="$1" want="$2" agent="$3"
  if [[ "$got" == "$want" ]]; then
    pass=$((pass+1))
    printf "  PASS  %-22s -> %s\n" "$agent" "$got"
  else
    fail=$((fail+1))
    printf "  FAIL  %-22s -> got=%s want=%s\n" "$agent" "$got" "$want"
  fi
}

echo "Reassigned agents (Layer A — design Section 3):"
report "$(agent_to_archetype GOLDDIGGER)" "exploration" "GOLDDIGGER"
report "$(agent_to_archetype ADVOCATE)"   "innovation"  "ADVOCATE"
report "$(agent_to_archetype VETERAN)"    "learning"    "VETERAN"

echo "Reassigned agents (Layer B — design Section 3):"
report "$(agent_to_archetype GUARDIAN)"   "validation"  "GUARDIAN"
report "$(agent_to_archetype BENCHMARK)"  "solution"    "BENCHMARK"
report "$(agent_to_archetype ORACLE)"     "solution"    "ORACLE"
report "$(agent_to_archetype MONITOR)"    "learning"    "MONITOR"

echo "Sanity (must NOT change):"
report "$(agent_to_archetype SCOUT)"       "exploration" "SCOUT"
report "$(agent_to_archetype SAGE)"        "validation"  "SAGE"
report "$(agent_to_archetype GATEKEEPER)"  "feasibility" "GATEKEEPER"
report "$(agent_to_archetype ARCHITECT)"   "solution"    "ARCHITECT"
report "$(agent_to_archetype IMPLEMENTER)" "build"       "IMPLEMENTER"
report "$(agent_to_archetype MAVERICK)"    "innovation"  "MAVERICK"
report "$(agent_to_archetype AUDITOR)"     "learning"    "AUDITOR"
report "$(agent_to_archetype COMMANDER)"   "control"     "COMMANDER"

echo
echo "Pass: $pass  Fail: $fail"
exit $((fail == 0 ? 0 : 1))
