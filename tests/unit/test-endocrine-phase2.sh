#!/usr/bin/env bash
# Unit tests — Phase 2: dopamine, cortisol, norepinephrine updates and gate events
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

approx() {
  awk -v v="$1" -v lo="$2" -v hi="$3" 'BEGIN { exit (v >= lo && v <= hi) ? 0 : 1 }'
}

# Initialize
run_endo init >/dev/null

# ---------------------------------------------------------------------------
# P2-01: get_hormone returns correct baseline for each index
# ---------------------------------------------------------------------------
# SCOUT is exploration: [0.4, 0.5, 0.4, 0.5, 0.5, 0.3]
val=$(run_endo get_hormone SCOUT 0)
if approx "$val" 0.39 0.41; then
  assert "P2-01: get_hormone SCOUT 0 (adrenaline) = ~0.4" "$(ok_result)"
else
  assert "P2-01: get_hormone SCOUT 0 (adrenaline) = ~0.4" "$(fail_result "got $val")"
fi

val=$(run_endo get_hormone SCOUT 1)
if approx "$val" 0.49 0.51; then
  assert "P2-01b: get_hormone SCOUT 1 (dopamine) = ~0.5" "$(ok_result)"
else
  assert "P2-01b: get_hormone SCOUT 1 (dopamine) = ~0.5" "$(fail_result "got $val")"
fi

val=$(run_endo get_hormone SCOUT 5)
if approx "$val" 0.29 0.31; then
  assert "P2-01c: get_hormone SCOUT 5 (norepinephrine) = ~0.3" "$(ok_result)"
else
  assert "P2-01c: get_hormone SCOUT 5 (norepinephrine) = ~0.3" "$(fail_result "got $val")"
fi

# ---------------------------------------------------------------------------
# P2-02: set_hormone clamps to [0.0, 1.0]
# ---------------------------------------------------------------------------
val=$(run_endo set_hormone SCOUT 1 1.5)
if approx "$val" 0.99 1.01; then
  assert "P2-02: set_hormone clamps 1.5 to 1.0" "$(ok_result)"
else
  assert "P2-02: set_hormone clamps 1.5 to 1.0" "$(fail_result "got $val")"
fi

val=$(run_endo set_hormone SCOUT 1 -0.5)
if approx "$val" -0.01 0.01; then
  assert "P2-02b: set_hormone clamps -0.5 to 0.0" "$(ok_result)"
else
  assert "P2-02b: set_hormone clamps -0.5 to 0.0" "$(fail_result "got $val")"
fi

# ---------------------------------------------------------------------------
# P2-03: set_hormone stores value correctly
# ---------------------------------------------------------------------------
val=$(run_endo set_hormone SCOUT 1 0.6)
if approx "$val" 0.59 0.61; then
  assert "P2-03: set_hormone SCOUT dopamine=0.6" "$(ok_result)"
else
  assert "P2-03: set_hormone SCOUT dopamine=0.6" "$(fail_result "got $val")"
fi
# Verify via get_hormone
val=$(run_endo get_hormone SCOUT 1)
if approx "$val" 0.59 0.61; then
  assert "P2-03b: get_hormone confirms dopamine=0.6" "$(ok_result)"
else
  assert "P2-03b: get_hormone confirms dopamine=0.6" "$(fail_result "got $val")"
fi

# ---------------------------------------------------------------------------
# P2-04: update_hormone adds delta with dampening
# ---------------------------------------------------------------------------
run_endo set_hormone SCOUT 2 0.5 >/dev/null  # cortisol = 0.5
val=$(run_endo update_hormone SCOUT 2 0.1)     # +0.1 → 0.6
if approx "$val" 0.59 0.61; then
  assert "P2-04: update_hormone cortisol +0.1 = 0.6" "$(ok_result)"
else
  assert "P2-04: update_hormone cortisol +0.1 = 0.6" "$(fail_result "got $val")"
fi

# ---------------------------------------------------------------------------
# P2-05: update_hormone dampens to max_change_per_cycle (0.3)
# ---------------------------------------------------------------------------
run_endo set_hormone SCOUT 2 0.5 >/dev/null
val=$(run_endo update_hormone SCOUT 2 0.5)  # 0.5 dampened to 0.3, result=0.8
if approx "$val" 0.79 0.81; then
  assert "P2-05: update_hormone dampens 0.5 to 0.3 (0.5+0.3=0.8)" "$(ok_result)"
else
  assert "P2-05: update_hormone dampens 0.5 to 0.3" "$(fail_result "got $val")"
fi

# ---------------------------------------------------------------------------
# P2-06: on_gate_pass increases dopamine by 0.15
# ---------------------------------------------------------------------------
run_endo init >/dev/null  # Reset to baselines
# IMPLEMENTER dopamine baseline = 0.5
before=$(run_endo get_hormone IMPLEMENTER 1)
run_endo on_gate_pass IMPLEMENTER >/dev/null
after=$(run_endo get_hormone IMPLEMENTER 1)
delta=$(awk -v a="$after" -v b="$before" 'BEGIN { printf "%.2f", a - b }')
if approx "$delta" 0.14 0.16; then
  assert "P2-06: on_gate_pass increases dopamine by ~0.15" "$(ok_result)"
else
  assert "P2-06: on_gate_pass increases dopamine by ~0.15" "$(fail_result "before=$before, after=$after, delta=$delta")"
fi

# ---------------------------------------------------------------------------
# P2-07: on_gate_fail decreases dopamine by 0.20 and increases cortisol by 0.10
# ---------------------------------------------------------------------------
run_endo init >/dev/null
dop_before=$(run_endo get_hormone IMPLEMENTER 1)
cor_before=$(run_endo get_hormone IMPLEMENTER 2)
run_endo on_gate_fail IMPLEMENTER >/dev/null
dop_after=$(run_endo get_hormone IMPLEMENTER 1)
cor_after=$(run_endo get_hormone IMPLEMENTER 2)
dop_delta=$(awk -v a="$dop_after" -v b="$dop_before" 'BEGIN { printf "%.2f", a - b }')
cor_delta=$(awk -v a="$cor_after" -v b="$cor_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$dop_delta" -0.21 -0.19; then
  assert "P2-07: on_gate_fail dopamine -0.20" "$(ok_result)"
else
  assert "P2-07: on_gate_fail dopamine -0.20" "$(fail_result "dop_delta=$dop_delta")"
fi
if approx "$cor_delta" 0.09 0.11; then
  assert "P2-07b: on_gate_fail cortisol +0.10" "$(ok_result)"
else
  assert "P2-07b: on_gate_fail cortisol +0.10" "$(fail_result "cor_delta=$cor_delta")"
fi

# ---------------------------------------------------------------------------
# P2-08: on_rework increases cortisol by 0.10
# ---------------------------------------------------------------------------
run_endo init >/dev/null
cor_before=$(run_endo get_hormone IMPLEMENTER 2)
run_endo on_rework IMPLEMENTER >/dev/null
cor_after=$(run_endo get_hormone IMPLEMENTER 2)
cor_delta=$(awk -v a="$cor_after" -v b="$cor_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$cor_delta" 0.09 0.11; then
  assert "P2-08: on_rework cortisol +0.10" "$(ok_result)"
else
  assert "P2-08: on_rework cortisol +0.10" "$(fail_result "cor_delta=$cor_delta")"
fi

# ---------------------------------------------------------------------------
# P2-09: on_low_confidence increases cortisol by 0.20
# ---------------------------------------------------------------------------
run_endo init >/dev/null
cor_before=$(run_endo get_hormone SAGE 2)
run_endo on_low_confidence SAGE >/dev/null
cor_after=$(run_endo get_hormone SAGE 2)
cor_delta=$(awk -v a="$cor_after" -v b="$cor_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$cor_delta" 0.19 0.21; then
  assert "P2-09: on_low_confidence cortisol +0.20" "$(ok_result)"
else
  assert "P2-09: on_low_confidence cortisol +0.20" "$(fail_result "cor_delta=$cor_delta")"
fi

# ---------------------------------------------------------------------------
# P2-10: on_innovate_summon decreases MAVERICK norepinephrine by 0.20
# ---------------------------------------------------------------------------
run_endo init >/dev/null
# MAVERICK innovation baseline norepinephrine = 0.2
nor_before=$(run_endo get_hormone MAVERICK 5)
run_endo on_innovate_summon >/dev/null
nor_after=$(run_endo get_hormone MAVERICK 5)
# 0.2 - 0.2 = 0.0 (clamped to floor)
if approx "$nor_after" -0.01 0.01; then
  assert "P2-10: on_innovate_summon MAVERICK norepinephrine → ~0.0" "$(ok_result)"
else
  assert "P2-10: on_innovate_summon MAVERICK norepinephrine → ~0.0" "$(fail_result "before=$nor_before, after=$nor_after")"
fi

# ---------------------------------------------------------------------------
# P2-11: invalid hormone index returns error
# ---------------------------------------------------------------------------
set +e
output=$(run_endo get_hormone SCOUT 6 2>&1)
rc=$?
set -e
if echo "$output" | grep -q "ERROR"; then
  assert "P2-11: invalid hormone index 6 returns error" "$(ok_result)"
else
  assert "P2-11: invalid hormone index 6 returns error" "$(fail_result "rc=$rc, output=$output")"
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
