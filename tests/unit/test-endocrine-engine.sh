#!/usr/bin/env bash
# Unit tests — Endocrine engine (endocrine.sh) functions
# Tests init, get, set, update, decay, circuit breaker (0.0-1.0 range)
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/runtime/scripts/bash"
ENDOCRINE="$SCRIPTS/endocrine.sh"

# Use a temporary directory to avoid polluting real state
TMPDIR_TEST=$(mktemp -d)
TEST_SQUAD_DIR="$TMPDIR_TEST/.specify/squad"
mkdir -p "$TEST_SQUAD_DIR"
echo '{}' > "$TEST_SQUAD_DIR/state.json"

# Export env vars so endocrine.sh picks them up
export ENDOCRINE_SQUAD_DIR="$TEST_SQUAD_DIR"
export ENDOCRINE_STATE_FILE="$TEST_SQUAD_DIR/state.json"
export ENDOCRINE_CONFIG_FILE="$REPO_ROOT/runtime/config-template.yml"

pass=0
fail=0

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1))
    printf 'FAIL: %s — %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result() { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

run_endo() {
  bash "$ENDOCRINE" "$@" 2>&1
}

# ---------------------------------------------------------------------------
# ENGINE-01: init creates endocrine_state in state.json
# ---------------------------------------------------------------------------
output=$(run_endo init)
if echo "$output" | grep -q "OK: endocrine state initialized"; then
  assert "ENGINE-01: init succeeds" "$(ok_result)"
else
  assert "ENGINE-01: init succeeds" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# ENGINE-02: init creates entries for known agents
# ---------------------------------------------------------------------------
agent_count=$(jq '.endocrine_state.agents | length' "$TEST_SQUAD_DIR/state.json" 2>/dev/null)
if [[ "$agent_count" -ge 30 ]]; then
  assert "ENGINE-02: init creates $agent_count agent entries (>=30)" "$(ok_result)"
else
  assert "ENGINE-02: init creates >=30 agent entries" "$(fail_result "got $agent_count")"
fi

# ---------------------------------------------------------------------------
# ENGINE-03: COMMANDER has archetype=control
# ---------------------------------------------------------------------------
arch=$(jq -r '.endocrine_state.agents.COMMANDER.archetype' "$TEST_SQUAD_DIR/state.json" 2>/dev/null)
if [[ "$arch" == "control" ]]; then
  assert "ENGINE-03: COMMANDER archetype is control" "$(ok_result)"
else
  assert "ENGINE-03: COMMANDER archetype is control" "$(fail_result "got $arch")"
fi

# ---------------------------------------------------------------------------
# ENGINE-04: IMPLEMENTER has archetype=build with adrenaline=0.6
# ---------------------------------------------------------------------------
arch=$(jq -r '.endocrine_state.agents.IMPLEMENTER.archetype' "$TEST_SQUAD_DIR/state.json" 2>/dev/null)
adr=$(jq -r '.endocrine_state.agents.IMPLEMENTER.hormones.adrenaline' "$TEST_SQUAD_DIR/state.json" 2>/dev/null)
if [[ "$arch" == "build" ]] && awk -v a="$adr" 'BEGIN { exit (a >= 0.59 && a <= 0.61) ? 0 : 1 }'; then
  assert "ENGINE-04: IMPLEMENTER is build/adrenaline=0.6" "$(ok_result)"
else
  assert "ENGINE-04: IMPLEMENTER is build/adrenaline=0.6" "$(fail_result "arch=$arch, adr=$adr")"
fi

# ---------------------------------------------------------------------------
# ENGINE-05: get_adrenaline returns correct value
# ---------------------------------------------------------------------------
val=$(run_endo get_adrenaline SCOUT)
if awk -v v="$val" 'BEGIN { exit (v >= 0.39 && v <= 0.41) ? 0 : 1 }'; then
  assert "ENGINE-05: get_adrenaline SCOUT returns ~0.4 (exploration baseline)" "$(ok_result)"
else
  assert "ENGINE-05: get_adrenaline SCOUT returns ~0.4" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-06: set_adrenaline clamps to ceiling (1.0)
# ---------------------------------------------------------------------------
val=$(run_endo set_adrenaline SCOUT 1.5)
if awk -v v="$val" 'BEGIN { exit (v >= 0.99 && v <= 1.01) ? 0 : 1 }'; then
  assert "ENGINE-06: set_adrenaline clamps 1.5 to ceiling 1.0" "$(ok_result)"
else
  assert "ENGINE-06: set_adrenaline clamps to ceiling" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-07: set_adrenaline clamps to floor (0.0)
# ---------------------------------------------------------------------------
val=$(run_endo set_adrenaline SCOUT -0.5)
if awk -v v="$val" 'BEGIN { exit (v >= -0.01 && v <= 0.01) ? 0 : 1 }'; then
  assert "ENGINE-07: set_adrenaline clamps -0.5 to floor 0.0" "$(ok_result)"
else
  assert "ENGINE-07: set_adrenaline clamps to floor" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-08: set_adrenaline accepts normal value
# ---------------------------------------------------------------------------
val=$(run_endo set_adrenaline SCOUT 0.5)
if awk -v v="$val" 'BEGIN { exit (v >= 0.49 && v <= 0.51) ? 0 : 1 }'; then
  assert "ENGINE-08: set_adrenaline stores 0.5" "$(ok_result)"
else
  assert "ENGINE-08: set_adrenaline stores 0.5" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-09: update_adrenaline adds delta
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.5 >/dev/null
val=$(run_endo update_adrenaline SCOUT 0.2)
if awk -v v="$val" 'BEGIN { exit (v >= 0.69 && v <= 0.71) ? 0 : 1 }'; then
  assert "ENGINE-09: update_adrenaline 0.5+0.2=0.7" "$(ok_result)"
else
  assert "ENGINE-09: update_adrenaline 0.5+0.2=0.7" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-10: update_adrenaline dampens large delta to max_change_per_cycle (0.3)
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.5 >/dev/null
val=$(run_endo update_adrenaline SCOUT 0.5)
# max_change_per_cycle=0.3, so 0.5 dampened to 0.3, result=0.8
if awk -v v="$val" 'BEGIN { exit (v >= 0.79 && v <= 0.81) ? 0 : 1 }'; then
  assert "ENGINE-10: update dampens delta 0.5 to max 0.3 (0.5+0.3=0.8)" "$(ok_result)"
else
  assert "ENGINE-10: update dampens delta 0.5 to max 0.3" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-11: decay_hormones moves toward baseline
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 1.0 >/dev/null
val=$(run_endo decay_hormones SCOUT)
# SCOUT baseline=0.4, decay=0.7: new = 0.4 + (1.0 - 0.4) * 0.7 = 0.4 + 0.42 = 0.82
if awk -v v="$val" 'BEGIN { exit (v >= 0.81 && v <= 0.83) ? 0 : 1 }'; then
  assert "ENGINE-11: decay from 1.0 toward baseline 0.4 gives ~0.82" "$(ok_result)"
else
  assert "ENGINE-11: decay from 1.0 toward baseline 0.4 gives ~0.82" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-12: decay applied twice converges further
# ---------------------------------------------------------------------------
val=$(run_endo decay_hormones SCOUT)
# new = 0.4 + (0.82 - 0.4) * 0.7 = 0.4 + 0.294 = 0.694 ≈ 0.69
if awk -v v="$val" 'BEGIN { exit (v >= 0.68 && v <= 0.71) ? 0 : 1 }'; then
  assert "ENGINE-12: second decay gives ~0.69" "$(ok_result)"
else
  assert "ENGINE-12: second decay gives ~0.69" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-13: check_circuit_breakers returns OK when not at extreme
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.5 >/dev/null
result=$(run_endo check_circuit_breakers SCOUT)
if echo "$result" | grep -q "^OK"; then
  assert "ENGINE-13: circuit breaker OK at normal value" "$(ok_result)"
else
  assert "ENGINE-13: circuit breaker OK at normal value" "$(fail_result "$result")"
fi

# ---------------------------------------------------------------------------
# ENGINE-14: check_circuit_breakers warns at ceiling
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 1.0 >/dev/null
result=$(run_endo check_circuit_breakers SCOUT)
if echo "$result" | grep -q "WARNING"; then
  assert "ENGINE-14: circuit breaker WARNING at ceiling" "$(ok_result)"
else
  assert "ENGINE-14: circuit breaker WARNING at ceiling" "$(fail_result "$result")"
fi

# ---------------------------------------------------------------------------
# ENGINE-15: circuit breaker resets after consecutive_extreme_reset cycles
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 1.0 >/dev/null
# Already 1 from ENGINE-14, need 2 more (total 3) for reset
run_endo check_circuit_breakers SCOUT >/dev/null  # consecutive=2
result=$(run_endo check_circuit_breakers SCOUT)     # consecutive=3 → RESET
if echo "$result" | grep -q "RESET"; then
  assert "ENGINE-15: circuit breaker RESET after 3 consecutive extreme" "$(ok_result)"
else
  assert "ENGINE-15: circuit breaker RESET after 3 consecutive extreme" "$(fail_result "$result")"
fi

# Verify adrenaline was actually reset to baseline
val=$(run_endo get_adrenaline SCOUT)
if awk -v v="$val" 'BEGIN { exit (v >= 0.39 && v <= 0.41) ? 0 : 1 }'; then
  assert "ENGINE-15b: SCOUT reset to baseline ~0.4" "$(ok_result)"
else
  assert "ENGINE-15b: SCOUT reset to baseline ~0.4" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-16: get_adrenaline for unknown agent returns error
# ---------------------------------------------------------------------------
set +e
output=$(run_endo get_adrenaline NONEXISTENT 2>&1)
rc=$?
set -e
if echo "$output" | grep -q "ERROR"; then
  assert "ENGINE-16: get_adrenaline NONEXISTENT returns error" "$(ok_result)"
else
  assert "ENGINE-16: get_adrenaline NONEXISTENT returns error" "$(fail_result "rc=$rc, output=$output")"
fi

# ---------------------------------------------------------------------------
# ENGINE-17: broadcast_adrenaline applies to all agents
# ---------------------------------------------------------------------------
# Reset all to baseline first
run_endo init >/dev/null
output=$(run_endo broadcast_adrenaline 0.1)
if echo "$output" | grep -q "OK: broadcast"; then
  assert "ENGINE-17: broadcast_adrenaline succeeds" "$(ok_result)"
else
  assert "ENGINE-17: broadcast_adrenaline succeeds" "$(fail_result "$output")"
fi

# Check that SCOUT (baseline 0.4) is now ~0.5 (0.4 + 0.1)
val=$(run_endo get_adrenaline SCOUT)
if awk -v v="$val" 'BEGIN { exit (v >= 0.49 && v <= 0.51) ? 0 : 1 }'; then
  assert "ENGINE-17b: SCOUT 0.4 + broadcast 0.1 = ~0.5" "$(ok_result)"
else
  assert "ENGINE-17b: SCOUT 0.4 + broadcast 0.1 = ~0.5" "$(fail_result "got '$val'")"
fi

# ---------------------------------------------------------------------------
# ENGINE-18: endocrine_state.initialized is true after init
# ---------------------------------------------------------------------------
init_flag=$(jq -r '.endocrine_state.initialized' "$TEST_SQUAD_DIR/state.json" 2>/dev/null)
if [[ "$init_flag" == "true" ]]; then
  assert "ENGINE-18: endocrine_state.initialized = true" "$(ok_result)"
else
  assert "ENGINE-18: endocrine_state.initialized = true" "$(fail_result "got '$init_flag'")"
fi

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
rm -rf "$TMPDIR_TEST"

echo ""
echo "=========================================="
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
echo "=========================================="
exit "$fail"
