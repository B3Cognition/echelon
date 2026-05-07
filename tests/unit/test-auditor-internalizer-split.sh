#!/usr/bin/env bash
# test-auditor-internalizer-split.sh — Verify the AUDITOR/INTERNALIZER split is correct
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== AUDITOR/INTERNALIZER Split Tests ==="
echo ""

# --- File existence ---
echo "--- File Existence ---"

if [[ -f "$REPO_ROOT/extension/agents/learning/auditor.md" ]]; then
  pass "auditor.md exists"
else
  fail "auditor.md does not exist"
fi

if [[ -f "$REPO_ROOT/extension/agents/learning/internalizer.md" ]]; then
  pass "internalizer.md exists"
else
  fail "internalizer.md does not exist"
fi

# --- AUDITOR should NOT contain internalization metric content ---
echo ""
echo "--- AUDITOR does NOT contain internalization keywords ---"

AUDITOR="$REPO_ROOT/extension/agents/learning/auditor.md"

for keyword in "I-01 requirement_coverage_rate" "I-05 numeric_contradiction_rate" \
               "I-09 confidence_accuracy" "I-13 first_pass_acceptance" \
               "Absorption Metrics" "int-Accuracy Metrics" "int-Calibration Metrics" \
               "int-Transfer Metrics" "Int-Gate Evaluation" "Cold-Start Check" \
               "Cross-Validation.*Goodhart" "Per-Agent Internalization Scoring" \
               "internalization-log.yaml entries"; do
  if grep -qE "$keyword" "$AUDITOR" 2>/dev/null; then
    fail "auditor.md still contains: $keyword"
  else
    pass "auditor.md does NOT contain: $keyword"
  fi
done

# --- AUDITOR should still contain calibration content ---
echo ""
echo "--- AUDITOR retains calibration content ---"

for keyword in "Domain Accuracy" "Correction Factors" "Confidence Data" \
               "calibration-profile.yaml" "Evolution Signal" "Calibration Dashboard"; do
  if grep -qE "$keyword" "$AUDITOR" 2>/dev/null; then
    pass "auditor.md contains: $keyword"
  else
    fail "auditor.md missing: $keyword"
  fi
done

# --- INTERNALIZER should contain internalization content ---
echo ""
echo "--- INTERNALIZER contains internalization keywords ---"

INTERNALIZER="$REPO_ROOT/extension/agents/learning/internalizer.md"

for keyword in "I-01 requirement_coverage_rate" "I-05 numeric_contradiction_rate" \
               "I-09 confidence_accuracy" "I-13 first_pass_acceptance" \
               "Absorption Metrics" "int-Accuracy Metrics" "int-Calibration Metrics" \
               "int-Transfer Metrics" "Int-Gate Evaluation" "Cold-Start Check" \
               "Cross-Validation" "Per-Agent Internalization Scoring" \
               "internalization-log.yaml"; do
  if grep -qE "$keyword" "$INTERNALIZER" 2>/dev/null; then
    pass "internalizer.md contains: $keyword"
  else
    fail "internalizer.md missing: $keyword"
  fi
done

# --- INTERNALIZER NEVER rules ---
echo ""
echo "--- INTERNALIZER NEVER rules ---"

if grep -q "NEVER modify calibration-profile.yaml" "$INTERNALIZER"; then
  pass "INTERNALIZER has NEVER rule about calibration-profile.yaml"
else
  fail "INTERNALIZER missing NEVER rule about calibration-profile.yaml"
fi

if grep -q "NEVER modify agent prompts" "$INTERNALIZER"; then
  pass "INTERNALIZER has NEVER rule about agent prompts"
else
  fail "INTERNALIZER missing NEVER rule about agent prompts"
fi

# --- extension.yml has INTERNALIZER ---
echo ""
echo "--- extension.yml registration ---"
EXT_YML="$REPO_ROOT/extension/extension.yml"
if grep -q "speckit.echelon.internalizer" "$EXT_YML" 2>/dev/null; then
  pass "INTERNALIZER registered in extension.yml"
else
  fail "INTERNALIZER not in extension.yml"
fi

# --- endocrine.sh has INTERNALIZER ---
echo ""
echo "--- endocrine.sh mapping ---"

ENDOCRINE="$REPO_ROOT/extension/scripts/bash/endocrine.sh"

if grep -q "INTERNALIZER" "$ENDOCRINE"; then
  pass "INTERNALIZER in endocrine.sh"
else
  fail "INTERNALIZER not in endocrine.sh"
fi

if grep -A1 -F "MIRROR|ADAPTIVE|AUDITOR|INTERNALIZER|REALIST" "$ENDOCRINE" | grep -q "learning"; then
  pass "INTERNALIZER mapped to learning archetype"
else
  fail "INTERNALIZER not mapped to learning archetype"
fi

# --- commander.md references INTERNALIZER ---
echo ""
echo "--- commander.md references ---"

COMMANDER="$REPO_ROOT/extension/agents/control/commander.md"

if grep -q "INTERNALIZER" "$COMMANDER"; then
  pass "INTERNALIZER referenced in commander.md"
else
  fail "INTERNALIZER not referenced in commander.md"
fi

if grep -q "INTERNALIZER Internalization Measurement" "$COMMANDER"; then
  pass "INTERNALIZER in FINALIZE dispatch sequence"
else
  fail "INTERNALIZER not in FINALIZE dispatch sequence"
fi

# --- Learning layer count updated ---
echo ""
echo "--- Agent count ---"

if grep -q "learning: 7" "$AGENTS_YAML"; then
  pass "Learning layer count updated to 7"
else
  fail "Learning layer count not updated to 7"
fi

if grep -q "total: 38" "$AGENTS_YAML"; then
  pass "Total agent count updated to 38"
else
  fail "Total agent count not updated to 38"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
