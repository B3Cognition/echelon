#!/usr/bin/env bash
# run_experiments.sh — One-shot experiment runner for spec 017 (NS-003 + U-CA-004)
#
# Prerequisites: export ANTHROPIC_API_KEY=sk-ant-...
#
# This script runs experiments in the correct order and checks the U-CA-004 verdict.
# If verdict is POSITIVE, Phase 5 (CA overlays) is automatically unblocked.
#
# Usage: bash scripts/run_experiments.sh [--n-ns003 30] [--n-uca004 20] [--verbose]

set -euo pipefail

N_NS003=30
N_UCA004=20
VERBOSE_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --n-ns003) N_NS003="$2"; shift 2 ;;
    --n-uca004) N_UCA004="$2"; shift 2 ;;
    --verbose) VERBOSE_FLAG="--verbose"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# Auth is handled via claude -p (Claude Code manages the key internally).
# No ANTHROPIC_API_KEY export needed — just run this script from the claude-code session.
if ! command -v claude &>/dev/null; then
  echo "ERROR: 'claude' CLI not found in PATH. Run this script inside a Claude Code session." >&2
  exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
mkdir -p "${REPO_ROOT}/experiments"

echo "============================================================"
echo "  Spec 017 Experiment Run"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# Step 1: NS-003 experiment (N=30)
# ---------------------------------------------------------------------------
echo "[1/2] Running NS-003 experiment (N=${N_NS003})..."
python3 "${REPO_ROOT}/scripts/ns003_experiment.py" \
  --n "${N_NS003}" \
  --schema-dir "${REPO_ROOT}/scripts/schemas/" \
  --output-dir "${REPO_ROOT}/experiments/" \
  --proceed-anyway \
  ${VERBOSE_FLAG}

echo ""
echo "NS-003 complete. Results at experiments/ns003-results.json"
echo "Report at experiments/ns003-report.md"
echo ""

# ---------------------------------------------------------------------------
# Step 2: U-CA-004 experiment (N=20 per condition)
# ---------------------------------------------------------------------------
echo "[2/2] Running U-CA-004 experiment (N=${N_UCA004} per condition)..."
python3 "${REPO_ROOT}/scripts/uca004_runner.py" \
  --n "${N_UCA004}" \
  --output-dir "${REPO_ROOT}/experiments/" \
  ${VERBOSE_FLAG}

echo ""
echo "U-CA-004 complete. Results at experiments/uca004-results.json"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Check verdict and run gate check
# ---------------------------------------------------------------------------
VERDICT=$(python3 -c "
import json
data = json.load(open('${REPO_ROOT}/experiments/uca004-results.json'))
print(data.get('verdict', 'MISSING'))
" 2>/dev/null)

echo "============================================================"
echo "  U-CA-004 VERDICT: ${VERDICT}"
echo "============================================================"
echo ""

if [[ "$VERDICT" == "POSITIVE" ]]; then
  echo "POSITIVE — CA overlay implementation is authorized."
  echo ""
  echo "Running CA overlay gate check..."
  bash "${REPO_ROOT}/scripts/ca/verify_gate.sh" --verbose
  echo ""
  echo "Next: build Phase 5 CA overlays (T-021 through T-026)."
  echo "Run: /speckit.echelon.build phase 5"
elif [[ "$VERDICT" == "NEGATIVE" ]]; then
  echo "NEGATIVE — CA overlay implementation is BLOCKED (P-020)."
  echo "See experiments/uca004-negative-report.md for details."
  echo ""
  echo "Phase 5 CA overlays will not be implemented."
elif [[ "$VERDICT" == "VOID" ]]; then
  echo "VOID — Insufficient completions (< 16 per condition)."
  echo "Re-run with a longer timeout or check API connectivity."
else
  echo "UNKNOWN verdict: ${VERDICT}"
fi

echo ""
echo "Build phase complete. Commit experiments/  to git when ready."
