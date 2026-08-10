#!/usr/bin/env bash
# Integration tests — Endocrine prompt modifier output (0.0-1.0 range)
# Tests that low/medium/high/critical adrenaline levels produce correct prompt text
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/runtime/scripts/bash"
ENDOCRINE="$SCRIPTS/endocrine.sh"

# Temp dir for isolated state
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

# Initialize state
run_endo init >/dev/null

# ---------------------------------------------------------------------------
# PROMPT-01: adrenaline=0.2 (LOW) produces LOW modifier
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.2 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=LOW"; then
  assert "PROMPT-01: adrenaline=0.2 produces LOW modifier" "$(ok_result)"
else
  assert "PROMPT-01: adrenaline=0.2 produces LOW modifier" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-02: LOW modifier mentions thoroughness
# ---------------------------------------------------------------------------
if echo "$output" | grep -qi "thorough"; then
  assert "PROMPT-02: LOW modifier mentions thoroughness" "$(ok_result)"
else
  assert "PROMPT-02: LOW modifier mentions thoroughness" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-03: adrenaline=0.5 (MEDIUM) produces MEDIUM modifier
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.5 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=MEDIUM"; then
  assert "PROMPT-03: adrenaline=0.5 produces MEDIUM modifier" "$(ok_result)"
else
  assert "PROMPT-03: adrenaline=0.5 produces MEDIUM modifier" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-04: MEDIUM modifier mentions balance
# ---------------------------------------------------------------------------
if echo "$output" | grep -qi "balance\|standard"; then
  assert "PROMPT-04: MEDIUM modifier mentions balance/standard" "$(ok_result)"
else
  assert "PROMPT-04: MEDIUM modifier mentions balance/standard" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-05: adrenaline=0.75 (HIGH) produces HIGH modifier
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.75 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=HIGH"; then
  assert "PROMPT-05: adrenaline=0.75 produces HIGH modifier" "$(ok_result)"
else
  assert "PROMPT-05: adrenaline=0.75 produces HIGH modifier" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-06: HIGH modifier mentions efficiency/concise
# ---------------------------------------------------------------------------
if echo "$output" | grep -qi "efficien\|concise"; then
  assert "PROMPT-06: HIGH modifier mentions efficiency/concise" "$(ok_result)"
else
  assert "PROMPT-06: HIGH modifier mentions efficiency/concise" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-07: adrenaline=0.95 (CRITICAL) produces CRITICAL modifier
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.95 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=CRITICAL"; then
  assert "PROMPT-07: adrenaline=0.95 produces CRITICAL modifier" "$(ok_result)"
else
  assert "PROMPT-07: adrenaline=0.95 produces CRITICAL modifier" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-08: CRITICAL modifier mentions emergency/finish
# ---------------------------------------------------------------------------
if echo "$output" | grep -qi "emergency\|finish\|NOW"; then
  assert "PROMPT-08: CRITICAL modifier mentions emergency/finish" "$(ok_result)"
else
  assert "PROMPT-08: CRITICAL modifier mentions emergency/finish" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-09: boundary — adrenaline=0.0 (LOW, floor)
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.0 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=LOW"; then
  assert "PROMPT-09: adrenaline=0.0 (floor) is LOW" "$(ok_result)"
else
  assert "PROMPT-09: adrenaline=0.0 (floor) is LOW" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-10: boundary — adrenaline=0.3 (MEDIUM, lower edge)
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.3 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=MEDIUM"; then
  assert "PROMPT-10: adrenaline=0.3 (boundary) is MEDIUM" "$(ok_result)"
else
  assert "PROMPT-10: adrenaline=0.3 (boundary) is MEDIUM" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-11: boundary — adrenaline=0.65 (HIGH, lower edge)
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.65 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=HIGH"; then
  assert "PROMPT-11: adrenaline=0.65 (boundary) is HIGH" "$(ok_result)"
else
  assert "PROMPT-11: adrenaline=0.65 (boundary) is HIGH" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-12: boundary — adrenaline=0.85 (CRITICAL, lower edge)
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.85 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=CRITICAL"; then
  assert "PROMPT-12: adrenaline=0.85 (boundary) is CRITICAL" "$(ok_result)"
else
  assert "PROMPT-12: adrenaline=0.85 (boundary) is CRITICAL" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-13: ceiling value (1.0) produces CRITICAL
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 1.0 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "adrenaline=CRITICAL"; then
  assert "PROMPT-13: adrenaline=1.0 (ceiling) is CRITICAL" "$(ok_result)"
else
  assert "PROMPT-13: adrenaline=1.0 (ceiling) is CRITICAL" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-14: modifier text starts with [ENDOCRINE: prefix
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.5 >/dev/null
output=$(run_endo get_prompt_modifier SCOUT)
if echo "$output" | grep -q "^\[ENDOCRINE:"; then
  assert "PROMPT-14: modifier starts with [ENDOCRINE: prefix" "$(ok_result)"
else
  assert "PROMPT-14: modifier starts with [ENDOCRINE: prefix" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# PROMPT-15: different agents at different levels produce different modifiers
# ---------------------------------------------------------------------------
run_endo set_adrenaline SCOUT 0.2 >/dev/null
run_endo set_adrenaline IMPLEMENTER 0.9 >/dev/null
scout_out=$(run_endo get_prompt_modifier SCOUT)
impl_out=$(run_endo get_prompt_modifier IMPLEMENTER)
if echo "$scout_out" | grep -q "LOW" && echo "$impl_out" | grep -q "CRITICAL"; then
  assert "PROMPT-15: SCOUT=LOW, IMPLEMENTER=CRITICAL (different modifiers)" "$(ok_result)"
else
  assert "PROMPT-15: different agents produce different modifiers" "$(fail_result "scout=$scout_out impl=$impl_out")"
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
