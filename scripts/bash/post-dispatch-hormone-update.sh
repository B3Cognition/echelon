#!/usr/bin/env bash
# post-dispatch-hormone-update.sh — Apply hormone-calc trigger output
# via endocrine.sh. Called by COMMANDER's Post-Dispatch Protocol after
# the standard A-C steps complete.
#
# Idempotent: skips re-application of dispatch_ids already in
# state.json.endocrine_state.applied_dispatches[].
#
# Usage:
#   bash post-dispatch-hormone-update.sh \
#     --agent SAGE --dispatch-id D-007 \
#     --result-file /tmp/echelon-result-D-007.yaml
#
# Exit codes:
#   0 = success (or graceful skip when endocrine.enabled=false)
#   1 = invalid arguments
#   2 = state.json or endocrine.sh not found

set -euo pipefail

HOOK_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
HOOK_REPO_ROOT="$(CDPATH='' cd "$HOOK_DIR/../.." && pwd)"

# --- arg parsing ---
AGENT=""; DISPATCH_ID=""; RESULT_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)        AGENT="$2"; shift 2 ;;
    --dispatch-id)  DISPATCH_ID="$2"; shift 2 ;;
    --result-file)  RESULT_FILE="$2"; shift 2 ;;
    -h|--help)      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "post-dispatch-hormone-update: unknown arg: $1" >&2; exit 1 ;;
  esac
done
if [[ -z "$AGENT" || -z "$DISPATCH_ID" || -z "$RESULT_FILE" ]]; then
  echo "Usage: post-dispatch-hormone-update.sh --agent X --dispatch-id Y --result-file Z" >&2
  exit 1
fi

# --- locate paths ---
ROOT="$(pwd)"
while [ "$ROOT" != "/" ] && [ ! -d "$ROOT/.echelon" ]; do
  ROOT=$(dirname "$ROOT")
done
if [ "$ROOT" = "/" ]; then
  echo "post-dispatch-hormone-update: no .echelon/ in CWD or parents" >&2
  exit 2
fi
cd "$ROOT"

RUNTIME_SCRIPTS="$ROOT/.echelon/runtime/scripts/bash"
if [[ ! -d "$RUNTIME_SCRIPTS" ]]; then
  RUNTIME_SCRIPTS="$HOOK_REPO_ROOT/runtime/scripts/bash"
fi
. "$RUNTIME_SCRIPTS/python-detect.sh"

find_squad_dir() {
  local root="$1" run_id current_file
  current_file="$root/runs/.current"
  if [[ -f "$current_file" ]]; then
    run_id=$(tr -d '[:space:]' < "$current_file")
    if [[ -n "$run_id" && -d "$root/runs/$run_id" ]]; then
      echo "$root/runs/$run_id"
      return 0
    fi
  fi
  echo "$root/runs"
}

SQUAD_DIR="${ENDOCRINE_SQUAD_DIR:-$(find_squad_dir "$ROOT")}"
STATE_FILE="${ENDOCRINE_STATE_FILE:-$SQUAD_DIR/state.json}"
ENDOCRINE_SH="$RUNTIME_SCRIPTS/endocrine.sh"
if [[ ! -f "$ENDOCRINE_SH" ]]; then
  echo "post-dispatch-hormone-update: endocrine.sh not found at $ENDOCRINE_SH" >&2
  exit 2
fi

JOURNAL_INDEX="$SQUAD_DIR/reasoning-journal-index.json"
JOURNAL="$SQUAD_DIR/reasoning-journal.jsonl"

mark_dispatch_applied() {
  if [[ -f "$STATE_FILE" ]] && command -v jq >/dev/null 2>&1; then
    local tmp
    tmp=$(mktemp)
    jq --arg did "$DISPATCH_ID" \
       '.endocrine_state.applied_dispatches = ((.endocrine_state.applied_dispatches // []) + [$did])' \
       "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
  fi
}

# --- graceful skip when endocrine disabled ---
ENABLED=$(bash "$RUNTIME_SCRIPTS/echelon-config-get.sh" endocrine.enabled 2>/dev/null || echo "true")
if [[ "$ENABLED" == "false" ]]; then
  exit 0
fi

# --- idempotency check ---
if [[ -f "$STATE_FILE" ]] && command -v jq >/dev/null 2>&1; then
  ALREADY=$(jq -r ".endocrine_state.applied_dispatches // [] | index(\"$DISPATCH_ID\")" "$STATE_FILE" 2>/dev/null)
  if [[ "$ALREADY" != "null" && -n "$ALREADY" ]]; then
    # Already applied — exit 0
    exit 0
  fi
fi

# A visible exact batch proves hormone actions completed before a prior crash.
set +e
"$PYTHON" -m harness.journal_entry_validator recover \
  --journal-path "$JOURNAL" \
  --rj-index "$JOURNAL_INDEX" \
  --batch-id "$DISPATCH_ID" >/dev/null 2>&1
RECOVERY_RC=$?
set -e
if [[ "$RECOVERY_RC" -eq 0 ]]; then
  mark_dispatch_applied
  echo "post-dispatch-hormone-update: recovered $DISPATCH_ID ($AGENT)"
  exit 0
elif [[ "$RECOVERY_RC" -ne 3 ]]; then
  echo "post-dispatch-hormone-update: journal recovery failed" >&2
  exit 1
fi

# --- capture BEFORE hormone snapshot for B-3 hormone_history trajectory tracking ---
BEFORE_HORMONES="{}"
if [[ -f "$STATE_FILE" ]] && command -v jq >/dev/null 2>&1; then
  BEFORE_HORMONES=$(jq -c ".endocrine_state.agents[\"$AGENT\"].hormones // {}" "$STATE_FILE" 2>/dev/null)
  [[ -z "$BEFORE_HORMONES" || "$BEFORE_HORMONES" == "null" ]] && BEFORE_HORMONES="{}"
fi

# --- map hormone name to index for hormone_update lines ---
hormone_index() {
  case "$1" in
    adrenaline) echo 0 ;;
    dopamine) echo 1 ;;
    cortisol) echo 2 ;;
    serotonin) echo 3 ;;
    oxytocin) echo 4 ;;
    norepinephrine) echo 5 ;;
    *) return 1 ;;
  esac
}

# --- invoke hormone-calc compute, capture triggers ---
TRIGGERS=$("$PYTHON" -m hormone_calc.cli compute \
  --agent "$AGENT" --dispatch-id "$DISPATCH_ID" \
  --result-file "$RESULT_FILE" \
  --state "$STATE_FILE" \
  --journal "$SQUAD_DIR/reasoning-journal.jsonl" 2>/dev/null) || {
  echo "post-dispatch-hormone-update: hormone-calc failed" >&2
  exit 1
}

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PHASE=$(jq -r '.phase // "unknown"' "$STATE_FILE" 2>/dev/null || echo "unknown")

applied_count=0
FIRED_VERBS=()
JOURNAL_ROWS=()
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  read -r verb arg1 arg2 arg3 <<< "$line"

  # Translate trigger line to endocrine.sh call.
  # Individual failures (e.g., agent not known to endocrine.sh) log a warning
  # but don't abort the hook — applied_dispatches[] must still be written so
  # idempotency holds on re-runs.
  case "$verb" in
    decay_hormones|on_gate_pass|on_gate_fail|on_rework|on_low_confidence|on_innovate_summon|on_quality_improvement|on_quality_regression)
      if ! bash "$ENDOCRINE_SH" "$verb" $arg1 >/dev/null 2>&1; then
        echo "post-dispatch-hormone-update: warning — $verb $arg1 failed (continuing)" >&2
      fi
      source_event="$verb"
      target="$arg1"
      ;;
    on_peer_accept|on_peer_reject|propagate_downstream|propagate_cortisol_contagion)
      if ! bash "$ENDOCRINE_SH" "$verb" "$arg1" "$arg2" >/dev/null 2>&1; then
        echo "post-dispatch-hormone-update: warning — $verb $arg1 $arg2 failed (continuing)" >&2
      fi
      source_event="$verb"
      target="$arg2"
      ;;
    hormone_update)
      if ! idx="$(hormone_index "$arg2")"; then
        echo "post-dispatch-hormone-update: unknown hormone '$arg2' (skipping)" >&2
        continue
      fi
      if ! bash "$ENDOCRINE_SH" update_hormone "$arg1" "$idx" "$arg3" >/dev/null 2>&1; then
        echo "post-dispatch-hormone-update: warning — update_hormone $arg1 $arg2 $arg3 failed (continuing)" >&2
      fi
      source_event="hormone_update_$arg2"
      target="$arg1"
      ;;
    broadcast_adrenaline)
      if ! bash "$ENDOCRINE_SH" broadcast_adrenaline "$arg1" >/dev/null 2>&1; then
        echo "post-dispatch-hormone-update: warning — broadcast_adrenaline $arg1 failed (continuing)" >&2
      fi
      source_event="broadcast_adrenaline"
      target="all"
      ;;
    *)
      echo "post-dispatch-hormone-update: unknown trigger verb '$verb' (skipping)" >&2
      continue
      ;;
  esac

  # Queue the whole journal batch; the shared Python store owns IDs and I/O.
  JOURNAL_ROWS+=("$(jq -cn \
    --arg phase "$PHASE" \
    --arg ts "$NOW" \
    --arg trigger "$verb" \
    --arg target "$target" \
    --arg did "$DISPATCH_ID" \
    --arg source_event "$source_event" \
    '{
      type: "endocrine_event",
      agent: "COMMANDER",
      phase: $phase,
      timestamp: $ts,
      data: {
        trigger: $trigger,
        target: $target,
        dispatch_id: $did,
        source_event: $source_event
      }
    }')")
  applied_count=$((applied_count + 1))
  FIRED_VERBS+=("$verb")
done <<< "$TRIGGERS"

# --- B-3: append hormone_history summary row for this dispatch ---
if [[ -f "$STATE_FILE" ]] && [[ "$applied_count" -gt 0 ]] && command -v jq >/dev/null 2>&1; then
  AFTER_HORMONES=$(jq -c ".endocrine_state.agents[\"$AGENT\"].hormones // {}" "$STATE_FILE" 2>/dev/null)
  [[ -z "$AFTER_HORMONES" || "$AFTER_HORMONES" == "null" ]] && AFTER_HORMONES="{}"

  # Build triggers JSON array
  TRIGGERS_JSON="["
  first=true
  for v in "${FIRED_VERBS[@]}"; do
    [[ "$first" == "true" ]] && first=false || TRIGGERS_JSON+=","
    TRIGGERS_JSON+="\"$v\""
  done
  TRIGGERS_JSON+="]"

  TMP=$(mktemp)
  jq --arg agent "$AGENT" \
     --arg did "$DISPATCH_ID" \
     --arg ts "$NOW" \
     --argjson before "$BEFORE_HORMONES" \
     --argjson after "$AFTER_HORMONES" \
     --argjson triggers "$TRIGGERS_JSON" \
     '.endocrine_state.hormone_history = ((.endocrine_state.hormone_history // []) + [
        {agent: $agent, dispatch_id: $did, timestamp: $ts, before: $before, after: $after, triggers: $triggers}
      ] | (if length > 200 then .[length-200:] else . end))' \
     "$STATE_FILE" > "$TMP"
  mv "$TMP" "$STATE_FILE"
fi

# The visible batch commits completed hormone and history mutations. Its
# index is repaired or adopted under the same shared fcntl lock on retry.
if [[ "$applied_count" -gt 0 ]]; then
  if ! printf '%s\n' "${JOURNAL_ROWS[@]}" | \
    "$PYTHON" -m harness.journal_entry_validator append \
      --journal-path "$JOURNAL" \
      --phase "$PHASE" \
      --input-format jsonl \
      --rj-index "$JOURNAL_INDEX" \
      --batch-id "$DISPATCH_ID" 2>/dev/null; then
    echo "post-dispatch-hormone-update: journal append failed" >&2
    exit 1
  fi
fi

# --- mark dispatch as applied (atomic state.json write) ---
mark_dispatch_applied

echo "post-dispatch-hormone-update: applied $applied_count triggers for $DISPATCH_ID ($AGENT)"
exit 0
