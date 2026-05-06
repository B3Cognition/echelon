#!/usr/bin/env bash
# Integration tests — get_full_prompt_modifier with various hormone combinations
set -uo pipefail
export LC_ALL=C

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
ENDOCRINE="$SCRIPTS/endocrine.sh"

TMPDIR_TEST=$(mktemp -d)
TEST_SQUAD_DIR="$TMPDIR_TEST/.specify/squad"
mkdir -p "$TEST_SQUAD_DIR"
echo '{}' > "$TEST_SQUAD_DIR/state.json"

export ENDOCRINE_SQUAD_DIR="$TEST_SQUAD_DIR"
export ENDOCRINE_STATE_FILE="$TEST_SQUAD_DIR/state.json"
export ENDOCRINE_CONFIG_FILE="$REPO_ROOT/extension/config-template.yml"

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

# Initialize
run_endo init >/dev/null

# ---------------------------------------------------------------------------
# FULL-01: all-medium hormones produce "all hormones MEDIUM" text
# ---------------------------------------------------------------------------
# COMMANDER is control: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5] — all medium
output=$(run_endo get_full_prompt_modifier COMMANDER)
if echo "$output" | grep -q "all hormones MEDIUM"; then
  assert "FULL-01: all-medium hormones produce neutral modifier" "$(ok_result)"
else
  assert "FULL-01: all-medium hormones produce neutral modifier" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-02: high adrenaline produces ADRENALINE=HIGH
# ---------------------------------------------------------------------------
run_endo set_hormone SCOUT 0 0.9 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "ADRENALINE=HIGH"; then
  assert "FULL-02: high adrenaline produces ADRENALINE=HIGH" "$(ok_result)"
else
  assert "FULL-02: high adrenaline produces ADRENALINE=HIGH" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-03: low dopamine produces DOPAMINE=LOW with strategy text
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 1 0.1 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "DOPAMINE=LOW"; then
  assert "FULL-03: low dopamine produces DOPAMINE=LOW" "$(ok_result)"
else
  assert "FULL-03: low dopamine produces DOPAMINE=LOW" "$(fail_result "$output")"
fi
if echo "$output" | grep -qi "different strategy"; then
  assert "FULL-03b: DOPAMINE=LOW mentions different strategy" "$(ok_result)"
else
  assert "FULL-03b: DOPAMINE=LOW mentions different strategy" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-04: high cortisol produces CORTISOL=HIGH with conservative text
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 2 0.85 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "CORTISOL=HIGH"; then
  assert "FULL-04: high cortisol produces CORTISOL=HIGH" "$(ok_result)"
else
  assert "FULL-04: high cortisol produces CORTISOL=HIGH" "$(fail_result "$output")"
fi
if echo "$output" | grep -qi "conservative"; then
  assert "FULL-04b: CORTISOL=HIGH mentions conservative" "$(ok_result)"
else
  assert "FULL-04b: CORTISOL=HIGH mentions conservative" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-05: low serotonin produces SEROTONIN=LOW with quality declining text
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 3 0.1 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "SEROTONIN=LOW"; then
  assert "FULL-05: low serotonin produces SEROTONIN=LOW" "$(ok_result)"
else
  assert "FULL-05: low serotonin produces SEROTONIN=LOW" "$(fail_result "$output")"
fi
if echo "$output" | grep -qi "declining"; then
  assert "FULL-05b: SEROTONIN=LOW mentions declining" "$(ok_result)"
else
  assert "FULL-05b: SEROTONIN=LOW mentions declining" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-06: high oxytocin produces OXYTOCIN=HIGH with trust text
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 4 0.9 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "OXYTOCIN=HIGH"; then
  assert "FULL-06: high oxytocin produces OXYTOCIN=HIGH" "$(ok_result)"
else
  assert "FULL-06: high oxytocin produces OXYTOCIN=HIGH" "$(fail_result "$output")"
fi
if echo "$output" | grep -qi "strong track record"; then
  assert "FULL-06b: OXYTOCIN=HIGH mentions track record" "$(ok_result)"
else
  assert "FULL-06b: OXYTOCIN=HIGH mentions track record" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-07: low norepinephrine produces NOREPINEPHRINE=LOW with explore text
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 5 0.1 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "NOREPINEPHRINE=LOW"; then
  assert "FULL-07: low norepinephrine produces NOREPINEPHRINE=LOW" "$(ok_result)"
else
  assert "FULL-07: low norepinephrine produces NOREPINEPHRINE=LOW" "$(fail_result "$output")"
fi
if echo "$output" | grep -qi "explore broadly"; then
  assert "FULL-07b: NOREPINEPHRINE=LOW mentions explore broadly" "$(ok_result)"
else
  assert "FULL-07b: NOREPINEPHRINE=LOW mentions explore broadly" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-08: multiple extreme hormones produce multiple modifiers
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 0 0.9 >/dev/null   # high adrenaline
run_endo set_hormone SCOUT 2 0.85 >/dev/null   # high cortisol
run_endo set_hormone SCOUT 5 0.1 >/dev/null    # low norepinephrine
output=$(run_endo get_full_prompt_modifier SCOUT)
has_adr=$(echo "$output" | grep -c "ADRENALINE=HIGH")
has_cor=$(echo "$output" | grep -c "CORTISOL=HIGH")
has_nor=$(echo "$output" | grep -c "NOREPINEPHRINE=LOW")
if [[ "$has_adr" -ge 1 && "$has_cor" -ge 1 && "$has_nor" -ge 1 ]]; then
  assert "FULL-08: multiple extreme hormones produce multiple modifiers" "$(ok_result)"
else
  assert "FULL-08: multiple extreme hormones produce multiple modifiers" "$(fail_result "adr=$has_adr, cor=$has_cor, nor=$has_nor")"
fi

# ---------------------------------------------------------------------------
# FULL-09: get_hormone_snapshot returns comma-separated values
# ---------------------------------------------------------------------------
run_endo init >/dev/null
snapshot=$(run_endo get_hormone_snapshot SCOUT)
# SCOUT exploration: [0.4, 0.5, 0.4, 0.5, 0.5, 0.3]
field_count=$(echo "$snapshot" | tr ',' '\n' | wc -l | tr -d ' ')
if [[ "$field_count" -eq 6 ]]; then
  assert "FULL-09: snapshot has 6 comma-separated values" "$(ok_result)"
else
  assert "FULL-09: snapshot has 6 comma-separated values" "$(fail_result "got $field_count: $snapshot")"
fi

# ---------------------------------------------------------------------------
# FULL-10: log_hormone_event appends to history
# ---------------------------------------------------------------------------
run_endo init >/dev/null
output=$(run_endo log_hormone_event SCOUT gate_pass)
if echo "$output" | grep -q "OK: logged"; then
  assert "FULL-10: log_hormone_event succeeds" "$(ok_result)"
else
  assert "FULL-10: log_hormone_event succeeds" "$(fail_result "$output")"
fi

history_len=$(jq '.endocrine_state.hormone_history | length' "$TEST_SQUAD_DIR/state.json")
if [[ "$history_len" -ge 1 ]]; then
  assert "FULL-10b: hormone_history has entry" "$(ok_result)"
else
  assert "FULL-10b: hormone_history has entry" "$(fail_result "len=$history_len")"
fi

# Check event details
ev_agent=$(jq -r '.endocrine_state.hormone_history[0].agent' "$TEST_SQUAD_DIR/state.json")
ev_type=$(jq -r '.endocrine_state.hormone_history[0].event_type' "$TEST_SQUAD_DIR/state.json")
if [[ "$ev_agent" == "SCOUT" && "$ev_type" == "gate_pass" ]]; then
  assert "FULL-10c: history entry has correct agent and event" "$(ok_result)"
else
  assert "FULL-10c: history entry has correct agent and event" "$(fail_result "agent=$ev_agent, type=$ev_type")"
fi

# ---------------------------------------------------------------------------
# FULL-11: log_hormone_event stores snapshot
# ---------------------------------------------------------------------------
ev_snap=$(jq -r '.endocrine_state.hormone_history[0].snapshot' "$TEST_SQUAD_DIR/state.json")
snap_fields=$(echo "$ev_snap" | tr ',' '\n' | wc -l | tr -d ' ')
if [[ "$snap_fields" -eq 6 ]]; then
  assert "FULL-11: logged event has 6-field snapshot" "$(ok_result)"
else
  assert "FULL-11: logged event has 6-field snapshot" "$(fail_result "fields=$snap_fields, snap=$ev_snap")"
fi

# ---------------------------------------------------------------------------
# FULL-12: multiple log events accumulate
# ---------------------------------------------------------------------------
run_endo log_hormone_event SCOUT gate_fail >/dev/null
run_endo log_hormone_event IMPLEMENTER rework >/dev/null
history_len=$(jq '.endocrine_state.hormone_history | length' "$TEST_SQUAD_DIR/state.json")
if [[ "$history_len" -ge 3 ]]; then
  assert "FULL-12: hormone_history accumulates ($history_len entries)" "$(ok_result)"
else
  assert "FULL-12: hormone_history accumulates" "$(fail_result "len=$history_len")"
fi

# ---------------------------------------------------------------------------
# FULL-13: MAVERICK baseline produces NOREPINEPHRINE=LOW (baseline 0.2)
# ---------------------------------------------------------------------------
run_endo init >/dev/null
output=$(run_endo get_full_prompt_modifier MAVERICK)
if echo "$output" | grep -q "NOREPINEPHRINE=LOW"; then
  assert "FULL-13: MAVERICK baseline norepinephrine=0.2 → LOW" "$(ok_result)"
else
  assert "FULL-13: MAVERICK baseline norepinephrine=0.2 → LOW" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-14: IMPLEMENTER baseline produces NOREPINEPHRINE=HIGH (baseline 0.8)
# ---------------------------------------------------------------------------
output=$(run_endo get_full_prompt_modifier IMPLEMENTER)
if echo "$output" | grep -q "NOREPINEPHRINE=HIGH"; then
  assert "FULL-14: IMPLEMENTER baseline norepinephrine=0.8 → HIGH" "$(ok_result)"
else
  assert "FULL-14: IMPLEMENTER baseline norepinephrine=0.8 → HIGH" "$(fail_result "$output")"
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
