#!/usr/bin/env bash
# pre-dispatch-gate.sh — Tier 1 rule enforcement gate
# Usage: ./scripts/bash/pre-dispatch-gate.sh --agent AGENT_NAME --task TASK_ID --state STATE_JSON [--temporal-store STORE_JSON]
# Exit 0 = ALLOW, Exit 1 = DENY (reason on stdout)
#
# Checks:
#   1. Phase sequence — agent is valid for the current phase
#   2. Retry count — agent has not exceeded max retries for this task
#   3. Temporal window — same agent+task not dispatched within last 60s
#   4. Fail-open — parse errors or missing files result in ALLOW with warning

set -uo pipefail

# ── Argument parsing ──────────────────────────────────────────────

AGENT=""
TASK=""
STATE=""
TEMPORAL_STORE=""
MAX_RETRIES=2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)          AGENT="$2";          shift 2 ;;
    --task)           TASK="$2";           shift 2 ;;
    --state)          STATE="$2";          shift 2 ;;
    --temporal-store) TEMPORAL_STORE="$2"; shift 2 ;;
    --max-retries)    MAX_RETRIES="$2";    shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 0 ;;  # fail-open
  esac
done

if [ -z "$AGENT" ] || [ -z "$TASK" ]; then
  echo "WARN: --agent and --task are required. Allowing dispatch (fail-open)." >&2
  exit 0
fi

# ── JSON query helper (jq preferred, python3 fallback) ────────────

json_query() {
  local file="$1" expr="$2"
  if command -v jq &>/dev/null; then
    jq -r "$expr" "$file" 2>/dev/null
  elif command -v python3 &>/dev/null; then
    python3 -c "
import json, sys
try:
    data = json.load(open('$file'))
    import functools
    # Evaluate a simple jq-like path: .key1.key2
    keys = '''$expr'''.strip('.').split('.')
    val = data
    for k in keys:
        if k == '':
            continue
        val = val[k] if isinstance(val, dict) and k in val else None
        if val is None:
            break
    print(val if val is not None else 'null')
except Exception:
    print('null')
" 2>/dev/null
  else
    echo "null"
  fi
}

# ── Valid agents per phase (bash 3 compatible) ────────────────────

agents_for_phase() {
  case "$1" in
    understand) echo "COMMANDER SCOUT SYNTHESIZER SAGE CARTOGRAPHER TRACKER CHECKPOINT SCOREKEEPER MONITOR" ;;
    decide)     echo "COMMANDER GATEKEEPER STRATEGIST CHECKPOINT TRACKER SCOREKEEPER MONITOR" ;;
    solution)   echo "COMMANDER ARCHITECT ORCHESTRATOR SENTINEL INVESTIGATOR GUARDIAN ORACLE BENCHMARK ADVOCATE MAVERICK SAGE SCOREKEEPER MONITOR" ;;
    build)      echo "COMMANDER IMPLEMENTER SPEC_GUARD CODE_REVIEWER TEST_GUARDIAN DEBUGGER INTEGRATOR PROGRESS_TRACKER CHANGE_CONTROLLER MODELER VALIDATOR MIRROR ADAPTIVE AUDITOR REALIST VETERAN MONITOR SCOREKEEPER" ;;
    *)          echo "" ;;  # Unknown phase — fail-open
  esac
}

# ── CHECK 1: Phase sequence ───────────────────────────────────────

if [ -n "$STATE" ] && [ -f "$STATE" ]; then
  PHASE=$(json_query "$STATE" ".phase")
  if [ "$PHASE" != "null" ] && [ -n "$PHASE" ]; then
    VALID=$(agents_for_phase "$PHASE")
    if [ -n "$VALID" ]; then
      if ! echo " $VALID " | grep -q " $AGENT "; then
        echo "DENY: Agent $AGENT is not valid for phase '$PHASE'. Valid agents: $VALID"
        exit 1
      fi
    fi
    # If phase not in map, allow (fail-open)
  fi
  # If phase is null or empty, allow (fail-open)
else
  echo "WARN: State file '${STATE:-<not specified>}' not found. Skipping phase check (fail-open)." >&2
fi

# ── CHECK 2: Retry count ─────────────────────────────────────────

if [ -n "$STATE" ] && [ -f "$STATE" ]; then
  if command -v jq &>/dev/null; then
    ATTEMPT_COUNT=$(jq -r \
      --arg agent "$AGENT" --arg task "$TASK" \
      '(.build.task_results[$task][$agent + "_attempts"] // 0) | tonumber' \
      "$STATE" 2>/dev/null || echo "0")
  elif command -v python3 &>/dev/null; then
    ATTEMPT_COUNT=$(python3 -c "
import json
try:
    data = json.load(open('$STATE'))
    count = data.get('build',{}).get('task_results',{}).get('$TASK',{}).get('${AGENT}_attempts', 0)
    print(int(count))
except Exception:
    print(0)
" 2>/dev/null || echo "0")
  else
    ATTEMPT_COUNT=0
    echo "WARN: No jq or python3 — skipping retry check (fail-open)." >&2
  fi

  if [ "$ATTEMPT_COUNT" -ge "$MAX_RETRIES" ] 2>/dev/null; then
    echo "DENY: $AGENT has exhausted $MAX_RETRIES retries on task '$TASK' (attempts: $ATTEMPT_COUNT)"
    exit 1
  fi
fi

# ── CHECK 3: Temporal window (anti-loop, 60s) ────────────────────

TEMPORAL_WINDOW=60

if [ -n "$TEMPORAL_STORE" ] && [ -f "$TEMPORAL_STORE" ]; then
  if command -v jq &>/dev/null; then
    LAST_TS=$(jq -r \
      --arg agent "$AGENT" --arg task "$TASK" \
      '[.[] | select(.agent==$agent and .task==$task) | .timestamp] | last // empty' \
      "$TEMPORAL_STORE" 2>/dev/null || echo "")
  elif command -v python3 &>/dev/null; then
    LAST_TS=$(python3 -c "
import json
try:
    data = json.load(open('$TEMPORAL_STORE'))
    matches = [f['timestamp'] for f in data if f.get('agent')=='$AGENT' and f.get('task')=='$TASK']
    print(matches[-1] if matches else '')
except Exception:
    print('')
" 2>/dev/null || echo "")
  else
    LAST_TS=""
    echo "WARN: No jq or python3 — skipping temporal check (fail-open)." >&2
  fi

  if [ -n "$LAST_TS" ]; then
    # Parse ISO timestamp to epoch — use python3 for reliable UTC handling
    if command -v python3 &>/dev/null; then
      LAST_EPOCH=$(python3 -c "
import datetime, sys
try:
    ts = '$LAST_TS'.replace('Z', '+00:00')
    dt = datetime.datetime.fromisoformat(ts)
    print(int(dt.timestamp()))
except Exception:
    print(0)
" 2>/dev/null || echo "0")
    elif date --version &>/dev/null 2>&1; then
      # GNU date
      LAST_EPOCH=$(date -d "$LAST_TS" +%s 2>/dev/null || echo "0")
    else
      # macOS/BSD date (TZ=UTC to handle Z suffix correctly)
      LAST_EPOCH=$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%SZ" "$LAST_TS" +%s 2>/dev/null || echo "0")
    fi
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST_EPOCH))

    if [ "$LAST_EPOCH" -gt 0 ] && [ "$ELAPSED" -lt "$TEMPORAL_WINDOW" ]; then
      echo "DENY: $AGENT was dispatched for task '$TASK' ${ELAPSED}s ago (window: ${TEMPORAL_WINDOW}s)"
      exit 1
    fi
  fi
else
  if [ -n "$TEMPORAL_STORE" ]; then
    echo "WARN: Temporal store '$TEMPORAL_STORE' not found. Skipping temporal check (fail-open)." >&2
  fi
fi

# ── ALL CHECKS PASSED ────────────────────────────────────────────

exit 0
