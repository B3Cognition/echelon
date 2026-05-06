#!/usr/bin/env bash
# Unit tests — Endocrine system config schema validation in config-template.yml
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$REPO_ROOT/extension/config-template.yml"

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

# ---------------------------------------------------------------------------
# SCHEMA-01: endocrine section exists
# ---------------------------------------------------------------------------
if grep -q '^endocrine:' "$CONFIG"; then
  assert "SCHEMA-01: endocrine section exists" "$(ok_result)"
else
  assert "SCHEMA-01: endocrine section exists" "$(fail_result 'endocrine: not found')"
fi

# ---------------------------------------------------------------------------
# SCHEMA-02: endocrine.enabled key exists and is boolean-like
# ---------------------------------------------------------------------------
val=$(awk '/^endocrine:/{found=1; next} found && /^[^ ]/{exit} found && /^  enabled:/{print $2; exit}' "$CONFIG" | tr -d ' ')
if [[ "$val" == "true" || "$val" == "false" ]]; then
  assert "SCHEMA-02: endocrine.enabled is boolean ($val)" "$(ok_result)"
else
  assert "SCHEMA-02: endocrine.enabled is boolean" "$(fail_result "got: '$val'")"
fi

# ---------------------------------------------------------------------------
# SCHEMA-03: endocrine.phase exists and is integer 1-4
# ---------------------------------------------------------------------------
val=$(awk '/^endocrine:/{found=1; next} found && /^[^ ]/{exit} found && /^  phase:/{print $2; exit}' "$CONFIG" | tr -d ' ')
if [[ "$val" =~ ^[1-4]$ ]]; then
  assert "SCHEMA-03: endocrine.phase is 1-4 ($val)" "$(ok_result)"
else
  assert "SCHEMA-03: endocrine.phase is 1-4" "$(fail_result "got: '$val'")"
fi

# ---------------------------------------------------------------------------
# SCHEMA-04: adrenaline triggers section exists with required keys
# ---------------------------------------------------------------------------
for key in budget_threshold budget_boost task_complexity_low task_complexity_high; do
  if grep -qE "^\s+${key}:" "$CONFIG"; then
    assert "SCHEMA-04: adrenaline.$key exists" "$(ok_result)"
  else
    assert "SCHEMA-04: adrenaline.$key exists" "$(fail_result 'not found')"
  fi
done

# ---------------------------------------------------------------------------
# SCHEMA-05: baselines section has all 8 archetypes
# ---------------------------------------------------------------------------
for archetype in exploration validation feasibility solution build innovation learning control; do
  if grep -qE "^\s+${archetype}:\s*\[" "$CONFIG"; then
    assert "SCHEMA-05: baseline.$archetype exists with array" "$(ok_result)"
  else
    assert "SCHEMA-05: baseline.$archetype exists with array" "$(fail_result 'not found')"
  fi
done

# ---------------------------------------------------------------------------
# SCHEMA-06: each baseline array has exactly 6 values
# ---------------------------------------------------------------------------
for archetype in exploration validation feasibility solution build innovation learning control; do
  arr=$(grep -E "^\s+${archetype}:\s*\[" "$CONFIG" | head -1 | sed 's/.*\[//' | sed 's/\].*//')
  count=$(echo "$arr" | tr ',' '\n' | wc -l | tr -d ' ')
  if [[ "$count" -eq 6 ]]; then
    assert "SCHEMA-06: baseline.$archetype has 6 hormones" "$(ok_result)"
  else
    assert "SCHEMA-06: baseline.$archetype has 6 hormones" "$(fail_result "got $count")"
  fi
done

# ---------------------------------------------------------------------------
# SCHEMA-07: circuit_breakers section has required keys
# ---------------------------------------------------------------------------
for key in max_change_per_cycle ceiling floor consecutive_extreme_reset; do
  if grep -qE "^\s+${key}:" "$CONFIG"; then
    assert "SCHEMA-07: circuit_breakers.$key exists" "$(ok_result)"
  else
    assert "SCHEMA-07: circuit_breakers.$key exists" "$(fail_result 'not found')"
  fi
done

# ---------------------------------------------------------------------------
# SCHEMA-08: decay section has all 6 hormone rates
# ---------------------------------------------------------------------------
for hormone in adrenaline dopamine cortisol serotonin oxytocin norepinephrine; do
  if grep -qE "^\s+${hormone}:\s*0\." "$CONFIG"; then
    assert "SCHEMA-08: decay.$hormone exists with decimal rate" "$(ok_result)"
  else
    assert "SCHEMA-08: decay.$hormone exists with decimal rate" "$(fail_result 'not found')"
  fi
done

# ---------------------------------------------------------------------------
# SCHEMA-09: ceiling > floor (0.0-1.0 range)
# ---------------------------------------------------------------------------
ceiling=$(awk '/circuit_breakers:/{found=1} found && /ceiling:/{print $2; exit}' "$CONFIG" | tr -d ' ')
floor=$(awk '/circuit_breakers:/{found=1} found && /floor:/{print $2; exit}' "$CONFIG" | tr -d ' ')
check=$(awk -v c="$ceiling" -v f="$floor" 'BEGIN { print (c > f) ? "yes" : "no" }')
if [[ "$check" == "yes" ]]; then
  assert "SCHEMA-09: ceiling ($ceiling) > floor ($floor)" "$(ok_result)"
else
  assert "SCHEMA-09: ceiling > floor" "$(fail_result "ceiling=$ceiling, floor=$floor")"
fi

# ---------------------------------------------------------------------------
# SCHEMA-10: all decay rates are in (0, 1)
# ---------------------------------------------------------------------------
all_ok=true
for hormone in adrenaline dopamine cortisol serotonin oxytocin norepinephrine; do
  rate=$(awk -v h="    ${hormone}:" '/^  decay:/{found=1; next} found && /^[^ ]/{exit} found && $0 ~ h{print $2; exit}' "$CONFIG" | tr -d ' ')
  valid=$(awk -v r="$rate" 'BEGIN { print (r > 0 && r < 1) ? "yes" : "no" }')
  if [[ "$valid" != "yes" ]]; then
    all_ok=false
    assert "SCHEMA-10: decay.$hormone in (0,1)" "$(fail_result "got $rate")"
  fi
done
if [[ "$all_ok" == "true" ]]; then
  assert "SCHEMA-10: all decay rates in (0,1)" "$(ok_result)"
fi

# ---------------------------------------------------------------------------
# SCHEMA-11: floor is 0.0 and ceiling is 1.0 (normalized range)
# ---------------------------------------------------------------------------
if [[ "$floor" == "0.0" || "$floor" == "0" ]]; then
  assert "SCHEMA-11: floor is 0.0 (normalized)" "$(ok_result)"
else
  assert "SCHEMA-11: floor is 0.0 (normalized)" "$(fail_result "got $floor")"
fi
if [[ "$ceiling" == "1.0" || "$ceiling" == "1" ]]; then
  assert "SCHEMA-11b: ceiling is 1.0 (normalized)" "$(ok_result)"
else
  assert "SCHEMA-11b: ceiling is 1.0 (normalized)" "$(fail_result "got $ceiling")"
fi

# ---------------------------------------------------------------------------
# SCHEMA-12: all baseline values are in [0.0, 1.0]
# ---------------------------------------------------------------------------
all_ok=true
for archetype in exploration validation feasibility solution build innovation learning control; do
  arr=$(grep -E "^\s+${archetype}:\s*\[" "$CONFIG" | head -1 | sed 's/.*\[//' | sed 's/\].*//')
  for val in $(echo "$arr" | tr ',' '\n'); do
    val=$(echo "$val" | tr -d ' ')
    valid=$(awk -v v="$val" 'BEGIN { print (v >= 0.0 && v <= 1.0) ? "yes" : "no" }')
    if [[ "$valid" != "yes" ]]; then
      all_ok=false
      assert "SCHEMA-12: baseline.$archetype value in [0,1]" "$(fail_result "$val out of range")"
      break
    fi
  done
done
if [[ "$all_ok" == "true" ]]; then
  assert "SCHEMA-12: all baseline values in [0.0, 1.0]" "$(ok_result)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
echo "=========================================="
exit "$fail"
