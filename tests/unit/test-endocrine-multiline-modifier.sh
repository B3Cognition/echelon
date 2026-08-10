#!/usr/bin/env bash
# Unit test — verify cmd_get_full_prompt_modifier emits the multi-line
# [ENDOCRINE — <archetype> archetype] format per spec section 2.
#
# Verifies T5's multi-line emit format end-to-end (was TDD-red prior to T5).

set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
ENDOCRINE="$REPO_ROOT/runtime/scripts/bash/endocrine.sh"

# Use ENDOCRINE_STATE_FILE to redirect state to a temp file — endocrine.sh
# respects this env var (see _endocrine_find_repo_root region of the script).
TMP_STATE=$(mktemp -t endocrine-multiline-state.XXXXXX.json)
trap 'rm -f "$TMP_STATE"' EXIT
echo "{}" > "$TMP_STATE"
export ENDOCRINE_STATE_FILE="$TMP_STATE"
export ENDOCRINE_CONFIG_FILE="$REPO_ROOT/runtime/echelon-config.yml"

# Seed all 41 agents' hormones from baselines.
bash "$ENDOCRINE" init >/dev/null 2>&1 || { echo "FAIL: endocrine.sh init failed"; exit 1; }

# Force GOLDDIGGER (post-T2 exploration archetype) into a state that triggers
# the cortisol_high overlay. We expect: cortisol HIGH, others remain MEDIUM-ish.
# Hormone indices: 0=adrenaline, 1=dopamine, 2=cortisol, 3=serotonin, 4=oxytocin, 5=norepinephrine
bash "$ENDOCRINE" set_hormone GOLDDIGGER 2 0.85 >/dev/null 2>&1   # cortisol HIGH
bash "$ENDOCRINE" set_hormone GOLDDIGGER 0 0.50 >/dev/null 2>&1   # adrenaline MEDIUM

# Get the modifier (strip stderr — DEP-FAIL-1 noise from `specify extension config` is harmless).
OUTPUT=$(bash "$ENDOCRINE" get_full_prompt_modifier GOLDDIGGER 2>/dev/null)

pass=0
fail=0
check() {
  local label="$1" pattern="$2"
  if echo "$OUTPUT" | grep -qE "$pattern"; then
    pass=$((pass+1))
    printf "  PASS  %s\n" "$label"
  else
    fail=$((fail+1))
    printf "  FAIL  %s  (no match for /%s/)\n" "$label" "$pattern"
  fi
}

echo "GOLDDIGGER (exploration archetype, cortisol HIGH at 0.85):"
check "multi-line archetype header"          "^\[ENDOCRINE — exploration archetype\]"
check "hormone line shows cortisol HIGH"     "cortisol:.*0\.8[0-9]+.*HIGH"
check "interpretation section header"        "Interpretation \(exploration archetype\):"
check "summary mentions curiosity"            "(curiosity|surface area|open threads)"
check "cortisol_high overlay triggered"       "HIGH cortisol.*([Ee]scalate|something is going wrong|going wrong)"

echo
echo "Output snapshot (for debugging when this test is red):"
echo "$OUTPUT" | sed 's/^/    /'
echo
echo "Pass: $pass  Fail: $fail"
exit $((fail == 0 ? 0 : 1))
