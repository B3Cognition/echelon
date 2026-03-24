#!/usr/bin/env bash
# Unit tests — Phase 3: serotonin, oxytocin, trust matrix, inter-agent propagation
set -uo pipefail
export LC_ALL=C

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts/bash"
ENDOCRINE="$SCRIPTS/endocrine.sh"

TMPDIR_TEST=$(mktemp -d)
TEST_SQUAD_DIR="$TMPDIR_TEST/.specify/squad"
mkdir -p "$TEST_SQUAD_DIR"
echo '{}' > "$TEST_SQUAD_DIR/state.json"

export ENDOCRINE_SQUAD_DIR="$TEST_SQUAD_DIR"
export ENDOCRINE_STATE_FILE="$TEST_SQUAD_DIR/state.json"
export ENDOCRINE_CONFIG_FILE="$REPO_ROOT/config-template.yml"

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
# P3-01: on_quality_improvement increases serotonin system-wide
# ---------------------------------------------------------------------------
ser_before=$(run_endo get_hormone SCOUT 3)
output=$(run_endo on_quality_improvement)
if echo "$output" | grep -q "OK: serotonin"; then
  assert "P3-01: on_quality_improvement succeeds" "$(ok_result)"
else
  assert "P3-01: on_quality_improvement succeeds" "$(fail_result "$output")"
fi

ser_after=$(run_endo get_hormone SCOUT 3)
delta=$(awk -v a="$ser_after" -v b="$ser_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$delta" 0.09 0.11; then
  assert "P3-01b: SCOUT serotonin increased by ~0.10" "$(ok_result)"
else
  assert "P3-01b: SCOUT serotonin increased by ~0.10" "$(fail_result "delta=$delta")"
fi

# Check another agent too
ser_impl=$(run_endo get_hormone IMPLEMENTER 3)
# IMPLEMENTER build baseline serotonin=0.5, +0.10 = 0.6
if approx "$ser_impl" 0.59 0.61; then
  assert "P3-01c: IMPLEMENTER serotonin also increased" "$(ok_result)"
else
  assert "P3-01c: IMPLEMENTER serotonin also increased" "$(fail_result "got $ser_impl")"
fi

# ---------------------------------------------------------------------------
# P3-02: on_quality_regression decreases serotonin system-wide
# ---------------------------------------------------------------------------
run_endo init >/dev/null
ser_before=$(run_endo get_hormone SCOUT 3)
output=$(run_endo on_quality_regression)
if echo "$output" | grep -q "OK: serotonin"; then
  assert "P3-02: on_quality_regression succeeds" "$(ok_result)"
else
  assert "P3-02: on_quality_regression succeeds" "$(fail_result "$output")"
fi

ser_after=$(run_endo get_hormone SCOUT 3)
delta=$(awk -v a="$ser_after" -v b="$ser_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$delta" -0.16 -0.14; then
  assert "P3-02b: SCOUT serotonin decreased by ~0.15" "$(ok_result)"
else
  assert "P3-02b: SCOUT serotonin decreased by ~0.15" "$(fail_result "delta=$delta")"
fi

# ---------------------------------------------------------------------------
# P3-03: on_peer_accept increases oxytocin and trust
# ---------------------------------------------------------------------------
run_endo init >/dev/null
oxy_arch_before=$(run_endo get_hormone ARCHITECT 4)
output=$(run_endo on_peer_accept ARCHITECT SENTINEL)
if echo "$output" | grep -q "OK: peer_accept"; then
  assert "P3-03: on_peer_accept succeeds" "$(ok_result)"
else
  assert "P3-03: on_peer_accept succeeds" "$(fail_result "$output")"
fi

oxy_arch_after=$(run_endo get_hormone ARCHITECT 4)
delta=$(awk -v a="$oxy_arch_after" -v b="$oxy_arch_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$delta" 0.04 0.06; then
  assert "P3-03b: ARCHITECT oxytocin +0.05" "$(ok_result)"
else
  assert "P3-03b: ARCHITECT oxytocin +0.05" "$(fail_result "delta=$delta")"
fi

# Check trust matrix
trust=$(run_endo get_trust ARCHITECT SENTINEL)
if approx "$trust" 0.54 0.56; then
  assert "P3-03c: trust ARCHITECT->SENTINEL = ~0.55" "$(ok_result)"
else
  assert "P3-03c: trust ARCHITECT->SENTINEL = ~0.55" "$(fail_result "got $trust")"
fi

# ---------------------------------------------------------------------------
# P3-04: on_peer_reject decreases oxytocin and trust
# ---------------------------------------------------------------------------
run_endo init >/dev/null
output=$(run_endo on_peer_reject IMPLEMENTER SPEC_GUARD)
if echo "$output" | grep -q "OK: peer_reject"; then
  assert "P3-04: on_peer_reject succeeds" "$(ok_result)"
else
  assert "P3-04: on_peer_reject succeeds" "$(fail_result "$output")"
fi

trust=$(run_endo get_trust IMPLEMENTER SPEC_GUARD)
if approx "$trust" 0.39 0.41; then
  assert "P3-04b: trust IMPLEMENTER->SPEC_GUARD = ~0.4" "$(ok_result)"
else
  assert "P3-04b: trust IMPLEMENTER->SPEC_GUARD = ~0.4" "$(fail_result "got $trust")"
fi

# ---------------------------------------------------------------------------
# P3-05: get_trust returns default 0.5 for unknown pair
# ---------------------------------------------------------------------------
trust=$(run_endo get_trust SCOUT SAGE)
if approx "$trust" 0.49 0.51; then
  assert "P3-05: default trust is 0.5" "$(ok_result)"
else
  assert "P3-05: default trust is 0.5" "$(fail_result "got $trust")"
fi

# ---------------------------------------------------------------------------
# P3-06: propagate_downstream transfers dopamine at 30%
# ---------------------------------------------------------------------------
run_endo init >/dev/null
# Set SCOUT dopamine to 0.8 (high output quality)
run_endo set_hormone SCOUT 1 0.8 >/dev/null
syn_dop_before=$(run_endo get_hormone SYNTHESIZER 1)
output=$(run_endo propagate_downstream SCOUT SYNTHESIZER)
if echo "$output" | grep -q "OK: propagated"; then
  assert "P3-06: propagate_downstream succeeds" "$(ok_result)"
else
  assert "P3-06: propagate_downstream succeeds" "$(fail_result "$output")"
fi

syn_dop_after=$(run_endo get_hormone SYNTHESIZER 1)
# delta = (0.8 - 0.5) * 0.3 = 0.09
delta=$(awk -v a="$syn_dop_after" -v b="$syn_dop_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$delta" 0.08 0.10; then
  assert "P3-06b: SYNTHESIZER dopamine increased by ~0.09" "$(ok_result)"
else
  assert "P3-06b: SYNTHESIZER dopamine increased by ~0.09" "$(fail_result "delta=$delta, before=$syn_dop_before, after=$syn_dop_after")"
fi

# ---------------------------------------------------------------------------
# P3-07: propagate_downstream with low dopamine decreases target
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SCOUT 1 0.2 >/dev/null  # low dopamine
syn_dop_before=$(run_endo get_hormone SYNTHESIZER 1)
run_endo propagate_downstream SCOUT SYNTHESIZER >/dev/null
syn_dop_after=$(run_endo get_hormone SYNTHESIZER 1)
# delta = (0.2 - 0.5) * 0.3 = -0.09
delta=$(awk -v a="$syn_dop_after" -v b="$syn_dop_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$delta" -0.10 -0.08; then
  assert "P3-07: low dopamine propagation decreases target by ~0.09" "$(ok_result)"
else
  assert "P3-07: low dopamine propagation decreases target" "$(fail_result "delta=$delta")"
fi

# ---------------------------------------------------------------------------
# P3-08: propagate_cortisol_contagion fires when cortisol > 0.8
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SAGE 2 0.9 >/dev/null  # high cortisol
cor_cart_before=$(run_endo get_hormone CARTOGRAPHER 2)
output=$(run_endo propagate_cortisol_contagion SAGE CARTOGRAPHER)
if echo "$output" | grep -q "+0.05"; then
  assert "P3-08: cortisol contagion fires at 0.9" "$(ok_result)"
else
  assert "P3-08: cortisol contagion fires at 0.9" "$(fail_result "$output")"
fi

cor_cart_after=$(run_endo get_hormone CARTOGRAPHER 2)
delta=$(awk -v a="$cor_cart_after" -v b="$cor_cart_before" 'BEGIN { printf "%.2f", a - b }')
if approx "$delta" 0.04 0.06; then
  assert "P3-08b: CARTOGRAPHER cortisol +0.05 from contagion" "$(ok_result)"
else
  assert "P3-08b: CARTOGRAPHER cortisol +0.05 from contagion" "$(fail_result "delta=$delta")"
fi

# ---------------------------------------------------------------------------
# P3-09: propagate_cortisol_contagion does NOT fire when cortisol <= 0.8
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo set_hormone SAGE 2 0.7 >/dev/null
output=$(run_endo propagate_cortisol_contagion SAGE CARTOGRAPHER)
if echo "$output" | grep -q "no contagion"; then
  assert "P3-09: no cortisol contagion at 0.7" "$(ok_result)"
else
  assert "P3-09: no cortisol contagion at 0.7" "$(fail_result "$output")"
fi

# ---------------------------------------------------------------------------
# P3-10: multiple peer_accept accumulates trust
# ---------------------------------------------------------------------------
run_endo init >/dev/null
run_endo on_peer_accept ARCHITECT SENTINEL >/dev/null  # 0.5 + 0.05 = 0.55
run_endo on_peer_accept ARCHITECT SENTINEL >/dev/null  # 0.55 + 0.05 = 0.60
trust=$(run_endo get_trust ARCHITECT SENTINEL)
if approx "$trust" 0.59 0.61; then
  assert "P3-10: trust accumulates to ~0.6 after 2 accepts" "$(ok_result)"
else
  assert "P3-10: trust accumulates to ~0.6 after 2 accepts" "$(fail_result "got $trust")"
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
