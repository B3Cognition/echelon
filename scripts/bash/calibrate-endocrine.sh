#!/usr/bin/env bash
# calibrate-endocrine.sh — Analyze hormone history from completed runs to suggest baseline adjustments
#
# Usage: calibrate-endocrine.sh [--state-dir DIR] [--min-runs N] [--output FILE]
#
# Reads hormone_history from state.json files (or a combined log), correlates
# hormone states at dispatch time with gate pass/fail outcomes, and outputs a
# report: which hormone levels correlated with success for each agent.
#
# Operators should run this after completing 10+ runs to tune baselines.
set -euo pipefail

# Force C locale for consistent decimal formatting
export LC_ALL=C

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

_resolve_run_dir() {
  local current_file run_id
  if [[ -n "${ECHELON_RUN_DIR:-}" ]]; then
    echo "$ECHELON_RUN_DIR"
    return 0
  fi

  current_file="$REPO_ROOT/runs/.current"
  if [[ -f "$current_file" ]]; then
    run_id=$(tr -d '[:space:]' < "$current_file")
    if [[ -n "$run_id" && -d "$REPO_ROOT/runs/$run_id" ]]; then
      echo "$REPO_ROOT/runs/$run_id"
      return 0
    fi
  fi

  echo "ERROR: No active Echelon run; pass --state-dir or create runs/.current." >&2
  return 1
}

STATE_DIR=""
MIN_RUNS=10
OUTPUT_FILE=""
VERBOSE=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --min-runs) MIN_RUNS="$2"; shift 2 ;;
    --output) OUTPUT_FILE="$2"; shift 2 ;;
    --verbose) VERBOSE=true; shift ;;
    -h|--help)
      echo "Usage: calibrate-endocrine.sh [--state-dir DIR] [--min-runs N] [--output FILE]"
      echo ""
      echo "Analyzes hormone_history from completed Echelon runs to suggest baseline adjustments."
      echo ""
      echo "Options:"
      echo "  --state-dir DIR    Directory containing state.json and backups/ (default: active run dir)"
      echo "  --min-runs N       Minimum number of runs required for analysis (default: 10)"
      echo "  --output FILE      Write report to FILE instead of stdout"
      echo "  --verbose          Print progress messages to stderr"
      echo "  -h, --help         Show this help"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$STATE_DIR" ]]; then
  STATE_DIR="$(_resolve_run_dir)"
fi

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required for calibrate-endocrine.sh" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Collect state files
# ---------------------------------------------------------------------------
STATE_FILES=()

# Current state.json
if [[ -f "$STATE_DIR/state.json" ]]; then
  STATE_FILES+=("$STATE_DIR/state.json")
fi

# Backup state files
if [[ -d "$STATE_DIR/backups" ]]; then
  while IFS= read -r f; do
    STATE_FILES+=("$f")
  done < <(find "$STATE_DIR/backups" -name 'state-*.json' -type f 2>/dev/null | sort)
fi

TOTAL_FILES=${#STATE_FILES[@]}
if [[ "$VERBOSE" == "true" ]]; then
  echo "Found $TOTAL_FILES state files to analyze" >&2
fi

if [[ $TOTAL_FILES -lt 1 ]]; then
  echo "ERROR: No state files found in $STATE_DIR" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Extract hormone events and gate outcomes
# ---------------------------------------------------------------------------
# We collect:
#   1. hormone_history entries (agent, hormone values at dispatch time)
#   2. Gate outcomes from dispatches (agent, verdict: pass/fail)

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Extract all hormone events from all state files
EVENTS_FILE="$TMPDIR/hormone_events.jsonl"
DISPATCHES_FILE="$TMPDIR/dispatches.jsonl"
: > "$EVENTS_FILE"
: > "$DISPATCHES_FILE"

RUN_COUNT=0

for sf in "${STATE_FILES[@]}"; do
  # Check if this file has hormone_history
  HAS_HISTORY=$(jq -r 'if .hormone_history then "yes" else "no" end' "$sf" 2>/dev/null || echo "no")
  if [[ "$HAS_HISTORY" == "yes" ]]; then
    jq -c '.hormone_history[]?' "$sf" >> "$EVENTS_FILE" 2>/dev/null || true
    RUN_COUNT=$((RUN_COUNT + 1))
  fi

  # Extract dispatches with token_ledger
  HAS_DISPATCHES=$(jq -r 'if .token_ledger.dispatches then "yes" else "no" end' "$sf" 2>/dev/null || echo "no")
  if [[ "$HAS_DISPATCHES" == "yes" ]]; then
    jq -c '.token_ledger.dispatches[]?' "$sf" >> "$DISPATCHES_FILE" 2>/dev/null || true
  fi
done

EVENT_COUNT=$(wc -l < "$EVENTS_FILE" | tr -d ' ')
DISPATCH_COUNT=$(wc -l < "$DISPATCHES_FILE" | tr -d ' ')

if [[ "$VERBOSE" == "true" ]]; then
  echo "Extracted $EVENT_COUNT hormone events, $DISPATCH_COUNT dispatches from $RUN_COUNT runs" >&2
fi

# ---------------------------------------------------------------------------
# Generate report
# ---------------------------------------------------------------------------
generate_report() {
  echo "# Endocrine Calibration Report"
  echo ""
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "State directory: $STATE_DIR"
  echo "State files analyzed: $TOTAL_FILES"
  echo "Runs with hormone data: $RUN_COUNT"
  echo "Total hormone events: $EVENT_COUNT"
  echo "Total dispatches: $DISPATCH_COUNT"
  echo ""

  if [[ $RUN_COUNT -lt $MIN_RUNS ]]; then
    echo "## Insufficient Data"
    echo ""
    echo "Only $RUN_COUNT runs found with hormone data. Minimum required: $MIN_RUNS."
    echo "Continue running Echelon sessions and re-run this script after $MIN_RUNS total runs."
    echo ""
    echo "### What to do next"
    echo "1. Run $((MIN_RUNS - RUN_COUNT)) more Echelon sessions with \`endocrine.enabled: true\` in .echelon/config.yml"
    echo "2. Re-run: \`scripts/bash/calibrate-endocrine.sh --state-dir $STATE_DIR\`"
    return
  fi

  echo "## Summary"
  echo ""

  # Per-agent hormone analysis
  echo "### Per-Agent Hormone Correlation"
  echo ""
  echo "| Agent | Avg Adrenaline at Success | Avg Adrenaline at Failure | Suggested Baseline | Delta |"
  echo "|-------|-------------------------|--------------------------|-------------------|-------|"

  # Extract unique agents from hormone events
  AGENTS=$(jq -r '.agent // empty' "$EVENTS_FILE" 2>/dev/null | sort -u)

  for agent in $AGENTS; do
    # Get adrenaline values for pass/fail events
    PASS_ADR=$(jq -r "select(.agent == \"$agent\" and .event_type == \"gate_pass\") | .adrenaline // empty" "$EVENTS_FILE" 2>/dev/null)
    FAIL_ADR=$(jq -r "select(.agent == \"$agent\" and .event_type == \"gate_fail\") | .adrenaline // empty" "$EVENTS_FILE" 2>/dev/null)

    # Compute averages (fallback to N/A)
    if [[ -n "$PASS_ADR" ]]; then
      AVG_PASS=$(echo "$PASS_ADR" | awk '{s+=$1; n++} END {if(n>0) printf "%.2f", s/n; else print "N/A"}')
    else
      AVG_PASS="N/A"
    fi

    if [[ -n "$FAIL_ADR" ]]; then
      AVG_FAIL=$(echo "$FAIL_ADR" | awk '{s+=$1; n++} END {if(n>0) printf "%.2f", s/n; else print "N/A"}')
    else
      AVG_FAIL="N/A"
    fi

    # Suggest baseline: midpoint of success range, biased toward success average
    if [[ "$AVG_PASS" != "N/A" && "$AVG_FAIL" != "N/A" ]]; then
      SUGGESTED=$(echo "$AVG_PASS $AVG_FAIL" | awk '{printf "%.2f", ($1 * 0.7 + $2 * 0.3)}')
      DELTA=$(echo "$AVG_PASS $AVG_FAIL" | awk '{d=$1-$2; if(d<0) d=-d; printf "%.2f", d}')
    elif [[ "$AVG_PASS" != "N/A" ]]; then
      SUGGESTED="$AVG_PASS"
      DELTA="N/A"
    else
      SUGGESTED="N/A"
      DELTA="N/A"
    fi

    echo "| $agent | $AVG_PASS | $AVG_FAIL | $SUGGESTED | $DELTA |"
  done

  echo ""
  echo "### Gate Outcome Distribution"
  echo ""

  TOTAL_PASS=$(jq -r 'select(.event_type == "gate_pass") | .agent' "$EVENTS_FILE" 2>/dev/null | wc -l | tr -d ' ')
  TOTAL_FAIL=$(jq -r 'select(.event_type == "gate_fail") | .agent' "$EVENTS_FILE" 2>/dev/null | wc -l | tr -d ' ')

  echo "- Gate passes: $TOTAL_PASS"
  echo "- Gate failures: $TOTAL_FAIL"
  if [[ $((TOTAL_PASS + TOTAL_FAIL)) -gt 0 ]]; then
    PASS_RATE=$(echo "$TOTAL_PASS $TOTAL_FAIL" | awk '{printf "%.1f", $1/($1+$2)*100}')
    echo "- Pass rate: ${PASS_RATE}%"
  fi

  echo ""
  echo "### Recommended Baseline Adjustments"
  echo ""
  echo "Apply these changes to \`.echelon/config.yml\` under \`endocrine.baselines\`:"
  echo ""
  echo "\`\`\`yaml"
  echo "endocrine:"
  echo "  baselines:"

  for agent in $AGENTS; do
    PASS_ADR=$(jq -r "select(.agent == \"$agent\" and .event_type == \"gate_pass\") | .adrenaline // empty" "$EVENTS_FILE" 2>/dev/null)
    if [[ -n "$PASS_ADR" ]]; then
      SUGGESTED=$(echo "$PASS_ADR" | awk '{s+=$1; n++} END {if(n>0) printf "%.1f", s/n; else print "5.0"}')
      echo "    # $agent: based on $RUN_COUNT runs"
      echo "    # $agent: [${SUGGESTED}, 5.0, 5.0, 5.0, 5.0, 5.0]  # [adr, dop, cor, ser, oxy, nor]"
    fi
  done

  echo "\`\`\`"
  echo ""
  echo "### Interpretation Guide"
  echo ""
  echo "- **High delta** (> 1.0) between success/failure adrenaline: strong signal that hormone level matters for this agent"
  echo "- **Low delta** (< 0.3): hormone level has weak correlation; baseline adjustment unlikely to help"
  echo "- **N/A values**: insufficient gate events for that agent; run more sessions"
  echo "- Agents with consistently high adrenaline at failure may benefit from LOWER baselines (they perform worse under pressure)"
  echo "- Agents with consistently high adrenaline at success may benefit from HIGHER baselines (they thrive under pressure)"
}

if [[ -n "$OUTPUT_FILE" ]]; then
  generate_report > "$OUTPUT_FILE"
  echo "Report written to: $OUTPUT_FILE" >&2
else
  generate_report
fi
