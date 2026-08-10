#!/usr/bin/env bash
# Unit test — verify agent_to_archetype assignments match spec section 3.
# Fails until Task 2 reassigns the 7 agents below.
# Uses subprocess pattern to call endocrine.sh get_archetype (avoiding source-time hazards).

set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
ENDOCRINE="$REPO_ROOT/runtime/scripts/bash/endocrine.sh"

if [[ ! -f "$ENDOCRINE" ]]; then
  echo "FAIL: $ENDOCRINE not found"
  exit 1
fi

archetype_of() {
  bash "$ENDOCRINE" get_archetype "$1" 2>/dev/null
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
report "$(archetype_of GOLDDIGGER)" "exploration" "GOLDDIGGER"
report "$(archetype_of ADVOCATE)"   "innovation"  "ADVOCATE"
report "$(archetype_of VETERAN)"    "learning"    "VETERAN"

echo "Reassigned agents (Layer B — design Section 3):"
report "$(archetype_of GUARDIAN)"   "validation"  "GUARDIAN"
report "$(archetype_of BENCHMARK)"  "solution"    "BENCHMARK"
report "$(archetype_of ORACLE)"     "solution"    "ORACLE"
report "$(archetype_of MONITOR)"    "learning"    "MONITOR"

echo "Sanity (must NOT change):"
report "$(archetype_of SCOUT)"       "exploration" "SCOUT"
report "$(archetype_of SAGE)"        "validation"  "SAGE"
report "$(archetype_of GATEKEEPER)"  "feasibility" "GATEKEEPER"
report "$(archetype_of ARCHITECT)"   "solution"    "ARCHITECT"
report "$(archetype_of IMPLEMENTER)" "build"       "IMPLEMENTER"
report "$(archetype_of MAVERICK)"    "innovation"  "MAVERICK"
report "$(archetype_of AUDITOR)"     "learning"    "AUDITOR"
report "$(archetype_of COMMANDER)"   "control"     "COMMANDER"

echo
echo "Pass: $pass  Fail: $fail"
exit $((fail == 0 ? 0 : 1))
