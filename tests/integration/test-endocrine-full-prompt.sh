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
# FULL-01: all-medium hormones (COMMANDER/control) produce multi-line block
# New format: [ENDOCRINE — control archetype] header with all MEDIUM hormones.
# The old "[ENDOCRINE: all hormones MEDIUM]" single-line is gone for archetypes
# that have an interpretations block; control archetype has one.
# ---------------------------------------------------------------------------
# COMMANDER is control: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5] — all medium
output=$(run_endo get_full_prompt_modifier COMMANDER)
if echo "$output" | grep -q "\[ENDOCRINE — control archetype\]"; then
  assert "FULL-01: all-medium hormones produce neutral modifier" "$(ok_result)"
else
  assert "FULL-01: all-medium hormones produce neutral modifier" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-02: high adrenaline shows (HIGH) in the hormone state header
# New format: "adrenaline: 0.90 (HIGH)" in the header line.
# Also produces an overlay line "- HIGH adrenaline: ..." for exploration archetype.
# ---------------------------------------------------------------------------
run_endo set_hormone SCOUT 0 0.9 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline:.*HIGH"; then
  assert "FULL-02: high adrenaline produces (HIGH) label in header" "$(ok_result)"
else
  assert "FULL-02: high adrenaline produces (HIGH) label in header" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-02b: high adrenaline produces the adrenaline overlay line
# Exploration archetype defines adrenaline_high overlay.
# ---------------------------------------------------------------------------
if echo "$output" | grep -q "HIGH adrenaline:"; then
  assert "FULL-02b: high adrenaline produces overlay line" "$(ok_result)"
else
  assert "FULL-02b: high adrenaline produces overlay line" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-03: low dopamine shows (LOW) in the hormone state header
# New format: "dopamine: 0.10 (LOW)" in the header line.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 1 0.1 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "dopamine:.*LOW"; then
  assert "FULL-03: low dopamine produces (LOW) label in header" "$(ok_result)"
else
  assert "FULL-03: low dopamine produces (LOW) label in header" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-03b: low dopamine produces the dopamine overlay line
# Exploration archetype defines dopamine_low overlay ("Curiosity slipping...").
# (Old assertion checked for "different strategy" — that text no longer appears.)
# ---------------------------------------------------------------------------
if echo "$output" | grep -q "LOW dopamine:"; then
  assert "FULL-03b: low dopamine produces overlay line" "$(ok_result)"
else
  assert "FULL-03b: low dopamine produces overlay line" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-04: high cortisol shows (HIGH) in the hormone state header
# New format: "cortisol: 0.85 (HIGH)" in the header line.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 2 0.85 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "cortisol:.*HIGH"; then
  assert "FULL-04: high cortisol produces (HIGH) label in header" "$(ok_result)"
else
  assert "FULL-04: high cortisol produces (HIGH) label in header" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-04b: high cortisol produces the cortisol overlay line
# Exploration archetype defines cortisol_high overlay ("Escalate to COMMANDER...").
# (Old assertion checked for "conservative" — that text no longer appears here.)
# ---------------------------------------------------------------------------
if echo "$output" | grep -q "HIGH cortisol:"; then
  assert "FULL-04b: high cortisol produces overlay line" "$(ok_result)"
else
  assert "FULL-04b: high cortisol produces overlay line" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-05: low serotonin shows (LOW) in the hormone state header
# Exploration archetype has no serotonin overlay — only the header-level
# classification is verifiable. The old SEROTONIN=LOW tag is gone.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 3 0.1 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "serotonin:.*LOW"; then
  assert "FULL-05: low serotonin shows (LOW) in header" "$(ok_result)"
else
  assert "FULL-05: low serotonin shows (LOW) in header" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-06: high oxytocin shows (HIGH) in the hormone state header
# Exploration archetype has no oxytocin overlay — only the header-level
# classification is verifiable. The old OXYTOCIN=HIGH tag is gone.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 4 0.9 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "oxytocin:.*HIGH"; then
  assert "FULL-06: high oxytocin shows (HIGH) in header" "$(ok_result)"
else
  assert "FULL-06: high oxytocin shows (HIGH) in header" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-07: low norepinephrine shows (LOW) in the hormone state header
# Exploration archetype has no norepinephrine overlay — only the header-level
# classification is verifiable. The old NOREPINEPHRINE=LOW tag is gone.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 5 0.1 >/dev/null
output=$(run_endo get_full_prompt_modifier SCOUT)
if echo "$output" | grep -q "norepinephrine:.*LOW"; then
  assert "FULL-07: low norepinephrine shows (LOW) in header" "$(ok_result)"
else
  assert "FULL-07: low norepinephrine shows (LOW) in header" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-08: multiple extreme hormones produce multiple overlay lines
# Exploration archetype has overlays for adrenaline_high and cortisol_high.
# norepinephrine_low has no overlay for exploration → not asserted.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 0 0.9 >/dev/null   # high adrenaline
run_endo set_hormone SCOUT 2 0.85 >/dev/null   # high cortisol
run_endo set_hormone SCOUT 5 0.1 >/dev/null    # low norepinephrine (no overlay)
output=$(run_endo get_full_prompt_modifier SCOUT)
has_adr=$(echo "$output" | grep -c "HIGH adrenaline:")
has_cor=$(echo "$output" | grep -c "HIGH cortisol:")
if [[ "$has_adr" -ge 1 && "$has_cor" -ge 1 ]]; then
  assert "FULL-08: multiple extreme hormones produce multiple overlay lines" "$(ok_result)"
else
  assert "FULL-08: multiple extreme hormones produce multiple overlay lines" "$(fail_result "adr_overlays=$has_adr, cor_overlays=$has_cor")"
fi

# ---------------------------------------------------------------------------
# FULL-09: get_hormone_snapshot returns comma-separated values
# run_endo merges stderr (which may contain "specify extension config" noise).
# Use tail -1 to extract the actual snapshot line.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
snapshot=$(run_endo get_hormone_snapshot SCOUT | tail -1)
# SCOUT exploration: [0.4, 0.5, 0.4, 0.5, 0.5, 0.3] at archetype baseline
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
# FULL-13: MAVERICK with norepinephrine=0.2 → shows (LOW) in header
# Innovation archetype baseline has norepinephrine=0.2 (LOW ≤ 0.25).
# Manually set to 0.2 since init may not apply archetype baselines in all envs.
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone MAVERICK 5 0.2 >/dev/null
output=$(run_endo get_full_prompt_modifier MAVERICK)
if echo "$output" | grep -q "norepinephrine:.*LOW"; then
  assert "FULL-13: MAVERICK norepinephrine=0.2 → LOW in header" "$(ok_result)"
else
  assert "FULL-13: MAVERICK norepinephrine=0.2 → LOW in header" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# FULL-14: IMPLEMENTER with norepinephrine=0.8 → shows (HIGH) in header
# Build archetype baseline has norepinephrine=0.8 (HIGH ≥ 0.75).
# Manually set to 0.8 since init may not apply archetype baselines in all envs.
# ---------------------------------------------------------------------------
run_endo set_hormone IMPLEMENTER 5 0.8 >/dev/null
output=$(run_endo get_full_prompt_modifier IMPLEMENTER)
if echo "$output" | grep -q "norepinephrine:.*HIGH"; then
  assert "FULL-14: IMPLEMENTER norepinephrine=0.8 → HIGH in header" "$(ok_result)"
else
  assert "FULL-14: IMPLEMENTER norepinephrine=0.8 → HIGH in header" "$(fail_result "$output")"
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
