#!/usr/bin/env bash
set -euo pipefail

# kb-validate-evolution.sh — Validate referential integrity, score consistency,
# and downstream completeness across the Knowledge Base evolution files.
#
# Exit 0 = all checks pass, Exit 1 = at least one ERROR found.
# Warnings (WARN) do not cause a non-zero exit.

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/python-detect.sh"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"
KB_DIR="$REPO_ROOT/knowledge-base"

AGENTS_YAML="$REPO_ROOT/extension/agents.yaml"
PROMPT_VERSIONS="$KB_DIR/prompt-versions.yaml"
INTERNALIZATION_LOG="$KB_DIR/internalization-log.yaml"
EVOLUTION_SIGNALS="$KB_DIR/evolution-signals.yaml"

# Config resolution: prefer spec-kit ConfigurationManager resolver.
# Falls back to direct YAML read when specify is unavailable.
CONFIG_FILE=""
_ECHELON_RESOLVER_OK=false
if command -v specify &>/dev/null; then
  # shellcheck disable=SC2046
  eval "$(specify extension config resolve echelon --format env --prefix ECHELON_CFG_)" 2>/dev/null \
    && _ECHELON_RESOLVER_OK=true
fi
if [[ "$_ECHELON_RESOLVER_OK" != "true" ]]; then
  if [[ -f "$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml" ]]; then
    CONFIG_FILE="$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml"
  else
    CONFIG_FILE="$SCRIPT_DIR/../../config-template.yml"
  fi
fi

STATE_FILE=""
ERRORS=0
WARNS=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--state path/to/state.json]

Validates Knowledge Base evolution files with 3 checks:

  Check 1: Cross-file referential integrity
    - Every internalization-log entry agent exists in agents.yaml
    - Every internalization-log entry prompt_version exists in prompt-versions.yaml
    - Every evolution-signals entry affected_agents exist in agents.yaml

  Check 2: Score/result consistency
    - Reads internalization thresholds from ECHELON_CFG_* (resolver) or .specify/extensions/echelon/echelon-config.yml
    - Verifies score and result (PASS/PARTIAL/FAIL) agree per threshold rules

  Check 3: Downstream outcome completeness (--state required)
    - If build is complete (phase: build_done|qa_in_progress|qa_failed|done),
      flags internalization-log entries with downstream_outcome: null as WARN

Options:
  --state PATH    Path to state.json (enables Check 3)
  -h, --help      Show this help

Exit codes:
  0  All checks passed (warnings are OK)
  1  At least one ERROR found
EOF
  exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --state)
      STATE_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

emit_error() {
  local file="$1" line="$2" msg="$3"
  printf '%s:%s: ERROR: %s\n' "$file" "$line" "$msg"
  ERRORS=$((ERRORS + 1))
}

emit_warn() {
  local file="$1" line="$2" msg="$3"
  printf '%s:%s: WARN: %s\n' "$file" "$line" "$msg"
  WARNS=$((WARNS + 1))
}

# ─────────────────────────────────────────────────────────────────────────────
# Check 1: Cross-file referential integrity
# ─────────────────────────────────────────────────────────────────────────────
check_referential_integrity() {
  echo "=== Check 1: Cross-file referential integrity ==="

  local _check1_out
  _check1_out=$($PYTHON - "$AGENTS_YAML" "$PROMPT_VERSIONS" "$INTERNALIZATION_LOG" "$EVOLUTION_SIGNALS" <<'PY'
import sys, yaml
from pathlib import Path

agents_path = Path(sys.argv[1])
pv_path     = Path(sys.argv[2])
ilog_path   = Path(sys.argv[3])
esig_path   = Path(sys.argv[4])

errors = 0

# Load agents.yaml — top-level keys under agents:
with open(agents_path) as f:
    agents_data = yaml.safe_load(f)
agent_names = set(agents_data.get('agents', {}).keys())

# Load prompt-versions.yaml — agents -> {AGENT: {versions: [{version: "X"}]}}
with open(pv_path) as f:
    pv_data = yaml.safe_load(f) or {}
pv_agents = pv_data.get('agents', {}) or {}
# Build set of (agent, version) pairs
valid_versions = set()
for agent_name, agent_info in pv_agents.items():
    for v in (agent_info or {}).get('versions', []) or []:
        valid_versions.add((agent_name, str(v.get('version', ''))))

# Load internalization-log.yaml
with open(ilog_path) as f:
    ilog_data = yaml.safe_load(f) or {}
ilog_entries = ilog_data.get('entries', []) or []

for i, entry in enumerate(ilog_entries):
    line = i + 1  # approximate line
    agent = entry.get('agent', '')
    if agent and agent not in agent_names:
        print(f"{ilog_path}:{line}: ERROR: agent '{agent}' not found in agents.yaml")
        errors += 1
    pv = str(entry.get('prompt_version', ''))
    if agent and pv and (agent, pv) not in valid_versions:
        print(f"{ilog_path}:{line}: ERROR: prompt_version '{pv}' for agent '{agent}' not found in prompt-versions.yaml")
        errors += 1

# Load evolution-signals.yaml
with open(esig_path) as f:
    esig_data = yaml.safe_load(f) or {}
esig_signals = esig_data.get('signals', []) or []

for i, sig in enumerate(esig_signals):
    line = i + 1
    affected = sig.get('affected_agents', []) or []
    for a in affected:
        if a not in agent_names:
            print(f"{esig_path}:{line}: ERROR: affected_agent '{a}' not found in agents.yaml")
            errors += 1

if errors == 0:
    print("  PASS — all references valid")
print(f"__ERRORS__:{errors}")
PY
)

  local rc
  rc=$(echo "$_check1_out" | grep '__ERRORS__:' | cut -d: -f2)
  echo "$_check1_out" | grep -v '__ERRORS__:'
  ERRORS=$((ERRORS + rc))
}

# ─────────────────────────────────────────────────────────────────────────────
# Check 2: Score/result consistency
# ─────────────────────────────────────────────────────────────────────────────
check_score_consistency() {
  echo "=== Check 2: Score/result consistency ==="

  local _check2_out
  # Pass thresholds via env: resolver-exported ECHELON_CFG_* takes precedence;
  # CONFIG_FILE is non-empty only when the resolver was unavailable.
  _check2_out=$(ECHELON_CFG_INTERNALIZATION_LEGACY_PASS_THRESHOLD="${ECHELON_CFG_INTERNALIZATION_LEGACY_PASS_THRESHOLD:-}" \
    ECHELON_CFG_INTERNALIZATION_LEGACY_PARTIAL_MIN="${ECHELON_CFG_INTERNALIZATION_LEGACY_PARTIAL_MIN:-}" \
    ECHELON_CFG_INTERNALIZATION_LEGACY_FAIL_BELOW="${ECHELON_CFG_INTERNALIZATION_LEGACY_FAIL_BELOW:-}" \
    $PYTHON - "${CONFIG_FILE:-}" "$INTERNALIZATION_LOG" <<'PY'
import sys, os, yaml
from pathlib import Path

config_arg  = sys.argv[1]
ilog_path   = Path(sys.argv[2])

errors = 0

# Read thresholds: prefer resolver-exported env vars, fall back to config file
pass_threshold = None
partial_min    = None
fail_below     = None

_pt = os.environ.get('ECHELON_CFG_INTERNALIZATION_LEGACY_PASS_THRESHOLD', '')
_pm = os.environ.get('ECHELON_CFG_INTERNALIZATION_LEGACY_PARTIAL_MIN', '')
_fb = os.environ.get('ECHELON_CFG_INTERNALIZATION_LEGACY_FAIL_BELOW', '')

if _pt and _pm and _fb:
    pass_threshold = float(_pt)
    partial_min    = float(_pm)
    fail_below     = float(_fb)
elif config_arg:
    with open(config_arg) as f:
        config = yaml.safe_load(f) or {}
    intern = config.get('internalization', {}).get('legacy', config.get('internalization', {})) or {}
    pass_threshold = float(intern.get('pass_threshold', 6))
    partial_min    = float(intern.get('partial_min', 4))
    fail_below     = float(intern.get('fail_below', 4))
else:
    pass_threshold, partial_min, fail_below = 6.0, 4.0, 4.0

# Read entries
with open(ilog_path) as f:
    ilog_data = yaml.safe_load(f) or {}
entries = ilog_data.get('entries', []) or []

for i, entry in enumerate(entries):
    line = i + 1
    score  = entry.get('score')
    result = entry.get('result')
    if score is None or result is None:
        continue

    score = float(score)
    expected = None
    if score >= pass_threshold:
        expected = 'PASS'
    elif score >= partial_min:
        expected = 'PARTIAL'
    else:
        expected = 'FAIL'

    if result != expected:
        print(f"{ilog_path}:{line}: ERROR: score={score} expects result={expected} but got result={result}")
        errors += 1

if errors == 0:
    print("  PASS — all scores consistent with results")
print(f"__ERRORS__:{errors}")
PY
)

  local rc
  rc=$(echo "$_check2_out" | grep '__ERRORS__:' | cut -d: -f2)
  echo "$_check2_out" | grep -v '__ERRORS__:'
  ERRORS=$((ERRORS + rc))
}

# ─────────────────────────────────────────────────────────────────────────────
# Check 3: Downstream outcome completeness (requires --state)
# ─────────────────────────────────────────────────────────────────────────────
check_downstream_completeness() {
  echo "=== Check 3: Downstream outcome completeness ==="

  if [[ -z "$STATE_FILE" ]]; then
    echo "  SKIP — no --state provided"
    return
  fi

  if [[ ! -f "$STATE_FILE" ]]; then
    emit_error "$STATE_FILE" 0 "state file not found"
    return
  fi

  $PYTHON - "$STATE_FILE" "$INTERNALIZATION_LOG" <<'PY'
import sys, json, yaml
from pathlib import Path

state_path = Path(sys.argv[1])
ilog_path  = Path(sys.argv[2])

warns = 0

with open(state_path) as f:
    state = json.load(f)

phase = state.get('phase', '')
complete_phases = {'build_done', 'qa_in_progress', 'qa_failed', 'done'}

if phase not in complete_phases:
    print(f"  SKIP — phase '{phase}' is not a completed build phase")
    sys.exit(0)

run_id = state.get('run_id', '')

with open(ilog_path) as f:
    ilog_data = yaml.safe_load(f) or {}
entries = ilog_data.get('entries', []) or []

for i, entry in enumerate(entries):
    line = i + 1
    entry_run = entry.get('run_id', '')
    if run_id and entry_run != run_id:
        continue
    outcome = entry.get('downstream_outcome')
    if outcome is None:
        agent = entry.get('agent', 'unknown')
        print(f"{ilog_path}:{line}: WARN: agent '{agent}' has downstream_outcome: null (build is {phase})")
        warns += 1

if warns == 0:
    print("  PASS — all downstream outcomes populated")
else:
    print(f"  {warns} warning(s) — downstream outcomes missing")

# Warnings do not cause non-zero exit
sys.exit(0)
PY
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
echo "kb-validate-evolution: validating Knowledge Base evolution files"
echo "  agents.yaml:           $AGENTS_YAML"
echo "  prompt-versions.yaml:  $PROMPT_VERSIONS"
echo "  internalization-log:   $INTERNALIZATION_LOG"
echo "  evolution-signals:     $EVOLUTION_SIGNALS"
echo "  config:                ${CONFIG_FILE:-echelon-config.yml (via resolver)}"
[[ -n "$STATE_FILE" ]] && echo "  state.json:            $STATE_FILE"
echo ""

check_referential_integrity
echo ""
check_score_consistency
echo ""
check_downstream_completeness
echo ""

if [[ $ERRORS -gt 0 ]]; then
  echo "FAILED: $ERRORS error(s), $WARNS warning(s)"
  exit 1
else
  echo "PASSED: 0 errors, $WARNS warning(s)"
  exit 0
fi
