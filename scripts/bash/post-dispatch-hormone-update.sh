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
while [ "$ROOT" != "/" ] && [ ! -d "$ROOT/.specify" ]; do
  ROOT=$(dirname "$ROOT")
done
if [ "$ROOT" = "/" ]; then
  echo "post-dispatch-hormone-update: no .specify/ in CWD or parents" >&2
  exit 2
fi
cd "$ROOT"

find_squad_dir() {
  local root="$1" base run_id current_file
  for base in runs squad; do
    current_file="$root/$base/.current"
    if [[ -f "$current_file" ]]; then
      run_id=$(tr -d '[:space:]' < "$current_file")
      if [[ -n "$run_id" && -d "$root/$base/$run_id" ]]; then
        echo "$root/$base/$run_id"
        return 0
      fi
    fi
  done
  echo "$root/.specify/squad"
}

SQUAD_DIR="${ENDOCRINE_SQUAD_DIR:-$(find_squad_dir "$ROOT")}"
STATE_FILE="${ENDOCRINE_STATE_FILE:-$SQUAD_DIR/state.json}"
ENDOCRINE_SH="$ROOT/extension/scripts/bash/endocrine.sh"
if [[ ! -f "$ENDOCRINE_SH" ]]; then
  echo "post-dispatch-hormone-update: endocrine.sh not found at $ENDOCRINE_SH" >&2
  exit 2
fi

# --- read current last_entry_id from journal index for sequential RJ-NNN ids ---
JOURNAL_INDEX="$SQUAD_DIR/reasoning-journal-index.json"
NEXT_RJ_NUM=1
if [[ -f "$JOURNAL_INDEX" ]] && command -v jq >/dev/null 2>&1; then
  last_id=$(jq -r '.last_entry_id // ""' "$JOURNAL_INDEX" 2>/dev/null)
  if [[ "$last_id" =~ ^RJ-([0-9]+)$ ]]; then
    NEXT_RJ_NUM=$((10#${BASH_REMATCH[1]} + 1))
  fi
fi

# --- graceful skip when endocrine disabled ---
ENABLED=$(bash "$ROOT/extension/scripts/bash/echelon-config-get.sh" endocrine.enabled 2>/dev/null || echo "true")
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
TRIGGERS=$(PYTHONPATH="$HOOK_REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m hormone_calc.cli compute \
  --agent "$AGENT" --dispatch-id "$DISPATCH_ID" \
  --result-file "$RESULT_FILE" \
  --state "$STATE_FILE" \
  --journal "$SQUAD_DIR/reasoning-journal.jsonl" 2>/dev/null) || {
  echo "post-dispatch-hormone-update: hormone-calc failed" >&2
  exit 1
}

JOURNAL="$SQUAD_DIR/reasoning-journal.jsonl"
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PHASE=$(jq -r '.phase // "unknown"' "$STATE_FILE" 2>/dev/null || echo "unknown")

applied_count=0
FIRED_VERBS=()
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

  # Append per-trigger journal entry
  rj_id=$(printf "RJ-%03d" "$NEXT_RJ_NUM")
  NEXT_RJ_NUM=$((NEXT_RJ_NUM + 1))
  printf '{"id":"%s","type":"endocrine_event","agent":"COMMANDER","phase":"%s","timestamp":"%s","data":{"trigger":"%s","target":"%s","dispatch_id":"%s","source_event":"%s"}}\n' \
    "$rj_id" "$PHASE" "$NOW" "$verb" "$target" "$DISPATCH_ID" "$source_event" >> "$JOURNAL"
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

# --- update journal index with the new last_entry_id (only if we emitted entries) ---
if [[ -f "$JOURNAL_INDEX" ]] && [[ "$applied_count" -gt 0 ]] && command -v jq >/dev/null 2>&1; then
  last_rj=$(printf "RJ-%03d" "$((NEXT_RJ_NUM - 1))")
  TMP=$(mktemp)
  jq --arg lid "$last_rj" '.last_entry_id = $lid' "$JOURNAL_INDEX" > "$TMP"
  mv "$TMP" "$JOURNAL_INDEX"
fi

# --- mark dispatch as applied (atomic state.json write) ---
if [[ -f "$STATE_FILE" ]] && command -v jq >/dev/null 2>&1; then
  TMP=$(mktemp)
  jq --arg did "$DISPATCH_ID" \
     '.endocrine_state.applied_dispatches = ((.endocrine_state.applied_dispatches // []) + [$did])' \
     "$STATE_FILE" > "$TMP"
  mv "$TMP" "$STATE_FILE"
fi

echo "post-dispatch-hormone-update: applied $applied_count triggers for $DISPATCH_ID ($AGENT)"
exit 0
