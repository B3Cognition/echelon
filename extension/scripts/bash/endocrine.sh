#!/usr/bin/env bash
# endocrine.sh — Hormone-modulated agent motivation engine (Phases 1-4)
#
# Usage:
#   endocrine.sh init                              — initialize endocrine state for all agents
#   endocrine.sh get_adrenaline <agent>            — return current adrenaline value
#   endocrine.sh set_adrenaline <agent> <value>    — set adrenaline (clamped)
#   endocrine.sh update_adrenaline <agent> <delta> — add delta to adrenaline (clamped, dampened)
#   endocrine.sh decay_hormones <agent>            — apply exponential decay toward baseline
#   endocrine.sh check_circuit_breakers <agent>    — check for runaway hormone states
#   endocrine.sh get_prompt_modifier <agent>       — return prompt modifier text based on adrenaline
#   endocrine.sh broadcast_adrenaline <delta>      — apply adrenaline delta to ALL agents
#   --- Phase 2 ---
#   endocrine.sh get_hormone <agent> <index>       — generic getter (0=adr,1=dop,2=cor,3=ser,4=oxy,5=nor)
#   endocrine.sh set_hormone <agent> <index> <val> — generic setter with clamping
#   endocrine.sh update_hormone <agent> <idx> <delta> — generic updater with dampening
#   endocrine.sh on_gate_pass <agent>              — dopamine +0.15
#   endocrine.sh on_gate_fail <agent>              — dopamine -0.20, cortisol +0.10
#   endocrine.sh on_rework <agent>                 — cortisol +0.10
#   endocrine.sh on_low_confidence <agent>         — cortisol +0.20
#   endocrine.sh on_innovate_summon                — norepinephrine -0.20 for MAVERICK
#   --- Phase 3 ---
#   endocrine.sh on_quality_improvement            — serotonin +0.10 system-wide
#   endocrine.sh on_quality_regression             — serotonin -0.15 system-wide
#   endocrine.sh on_peer_accept <from> <to>        — oxytocin +0.05 for the pair
#   endocrine.sh on_peer_reject <from> <to>        — oxytocin -0.10 for the pair
#   endocrine.sh propagate_downstream <from> <to>  — propagate dopamine at 30% strength
#   endocrine.sh propagate_cortisol_contagion <from> <to> — if from.cortisol > 0.8, add +0.05 to target
#   endocrine.sh get_trust <from> <to>             — read pairwise oxytocin from trust_matrix
#   endocrine.sh get_full_prompt_modifier <agent>  — returns modifiers for ALL 6 hormones
#   --- Phase 4 ---
#   endocrine.sh get_hormone_snapshot <agent>      — returns all 6 values as comma-separated
#   endocrine.sh log_hormone_event <agent> <event> — appends to hormone_history in state.json
#
# Reads config via `specify extension config resolve echelon` (preferred).
# Falls back to direct YAML read from .specify/extensions/echelon/echelon-config.yml when specify is unavailable.
# State stored in runs/spec-<run-id>/state.json under "endocrine_state" (auto-detected via runs/.current).
set -euo pipefail
. "$(CDPATH='' cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/python-detect.sh"

# Force C locale for consistent decimal formatting (avoid locale comma separators)
export LC_ALL=C

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect project root by walking up from pwd until .specify/ is found.
# This works in both dev context (script at extension/scripts/bash/) and
# installed context (script at .specify/extensions/echelon/scripts/bash/).
# The 3-level fallback covers dev mode where no .specify exists in the tree.
_endocrine_find_repo_root() {
  local dir
  dir="$(pwd)"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/.specify" ]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  # Fallback for dev/test: 3 levels up from the script file
  CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd
}
REPO_ROOT="${ENDOCRINE_REPO_ROOT:-$(_endocrine_find_repo_root)}"

# Detect the active spec run from runs/.current (primary layout).
# Falls back to legacy squad/.current for pre-migration installs.
_endocrine_find_squad_dir() {
  local root="$1"
  local base run_id current_file
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
SQUAD_DIR="${ENDOCRINE_SQUAD_DIR:-$(_endocrine_find_squad_dir "$REPO_ROOT")}"
STATE_FILE="${ENDOCRINE_STATE_FILE:-$SQUAD_DIR/state.json}"

# Config resolution: prefer spec-kit ConfigurationManager resolver.
# Falls back to direct YAML read when specify is unavailable (test/offline use).
_ECHELON_RESOLVER_OK=false
if command -v specify &>/dev/null; then
  # Capture resolver stdout, then only eval + mark OK when it actually emitted
  # at least one ECHELON_CFG_* line. The naive `&& _ECHELON_RESOLVER_OK=true`
  # pattern wrongly succeeds on a `specify` that exits non-zero but still prints
  # to stdout (e.g. when `config resolve` is missing from the installed CLI),
  # which silently defaults every agent's hormones to 0.5 because get_baseline
  # then never reaches the CONFIG_FILE fallback.
  if _resolver_out=$(specify extension config resolve echelon --format env --prefix ECHELON_CFG_ 2>/dev/null); then
    if [[ -n "$_resolver_out" ]] && printf '%s\n' "$_resolver_out" | grep -q '^ECHELON_CFG_'; then
      # shellcheck disable=SC1090
      eval "$_resolver_out"
      _ECHELON_RESOLVER_OK=true
    fi
  fi
  unset _resolver_out
fi

if [[ "$_ECHELON_RESOLVER_OK" != "true" ]]; then
  # Fallback: read from project config (resolver's source) or bundled defaults.
  # The source config is included in the chain BEFORE config-template.yml so
  # CI checkouts (where .specify/extensions/ is gitignored) still resolve
  # correct archetype baselines. Same fix shape as commit df99b73 / 5c2f653.
  if [[ -n "${ENDOCRINE_CONFIG_FILE:-}" ]]; then
    CONFIG_FILE="$ENDOCRINE_CONFIG_FILE"
  elif [[ -f "$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml" ]]; then
    CONFIG_FILE="$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml"
  elif [[ -f "$REPO_ROOT/extension/echelon-config.yml" ]]; then
    CONFIG_FILE="$REPO_ROOT/extension/echelon-config.yml"
  else
    CONFIG_FILE="$SCRIPT_DIR/../../config-template.yml"
  fi
fi

# ---------------------------------------------------------------------------
# Helpers — lightweight YAML/JSON reading without yq/jq dependency issues
# ---------------------------------------------------------------------------

# Read a simple scalar from YAML (handles "key: value" on its own line)
yaml_get() {
  local file="$1" key="$2"
  grep -E "^\s+${key}:" "$file" 2>/dev/null | head -1 | sed 's/.*: *//' | sed 's/#.*//' | tr -d ' '
}

# Read a YAML array line like "exploration: [4.0, 5.0, 4.0, 5.0, 5.0, 3.0]"
yaml_get_array() {
  local file="$1" key="$2"
  grep -E "^\s+${key}:" "$file" 2>/dev/null | head -1 | sed 's/.*\[//' | sed 's/\].*//' | tr -d ' '
}

# Requires jq for state.json manipulation
require_jq() {
  if ! command -v jq &>/dev/null; then
    echo "ERROR: jq is required for endocrine.sh" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Hormone names by index
# ---------------------------------------------------------------------------
HORMONE_NAMES=(adrenaline dopamine cortisol serotonin oxytocin norepinephrine)

hormone_name_by_index() {
  local idx="$1"
  if [[ "$idx" -ge 0 && "$idx" -lt 6 ]]; then
    echo "${HORMONE_NAMES[$idx]}"
  else
    echo "ERROR: hormone index must be 0-5, got $idx" >&2
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Config readers
# ---------------------------------------------------------------------------

get_enabled() {
  local val="${ECHELON_CFG_ENDOCRINE_ENABLED:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/^endocrine:/{found=1} found && /^\s+enabled:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-true}"
}

get_phase() {
  local val="${ECHELON_CFG_ENDOCRINE_PHASE:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/^endocrine:/{found=1} found && /^\s+phase:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-3}"
}

get_ceiling() {
  local val="${ECHELON_CFG_ENDOCRINE_CIRCUIT_BREAKERS_CEILING:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/circuit_breakers:/{found=1} found && /ceiling:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-1.0}"
}

get_floor() {
  local val="${ECHELON_CFG_ENDOCRINE_CIRCUIT_BREAKERS_FLOOR:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/circuit_breakers:/{found=1} found && /floor:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-0.0}"
}

get_max_change() {
  local val="${ECHELON_CFG_ENDOCRINE_CIRCUIT_BREAKERS_MAX_CHANGE_PER_CYCLE:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/circuit_breakers:/{found=1} found && /max_change_per_cycle:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-0.4}"
}

get_consecutive_extreme_reset() {
  local val="${ECHELON_CFG_ENDOCRINE_CIRCUIT_BREAKERS_CONSECUTIVE_EXTREME_RESET:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/circuit_breakers:/{found=1} found && /consecutive_extreme_reset:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-5}"
}

get_decay_rate() {
  local hormone="$1"
  local env_key="ECHELON_CFG_ENDOCRINE_DECAY_$(echo "$hormone" | tr '[:lower:]' '[:upper:]')"
  local val="${!env_key:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk -v h="$hormone" '
      /^  decay:/ { in_decay=1; next }
      in_decay && /^  [^ ]/ { exit }
      in_decay && $0 ~ "^    " h ":" { print $2; exit }
    ' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "$val"
}

get_budget_threshold() {
  local val="${ECHELON_CFG_ENDOCRINE_ADRENALINE_BUDGET_THRESHOLD:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/^\s+adrenaline:/{found=1} found && /budget_threshold:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-0.85}"
}

get_budget_boost() {
  local val="${ECHELON_CFG_ENDOCRINE_ADRENALINE_BUDGET_BOOST:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk '/^\s+adrenaline:/{found=1} found && /budget_boost:/{print $2; exit}' "$CONFIG_FILE" | tr -d ' ')
  fi
  echo "${val:-0.3}"
}

# Get baseline array for an archetype (returns comma-separated)
get_baseline() {
  local archetype="$1"
  local env_key="ECHELON_CFG_ENDOCRINE_BASELINES_$(echo "$archetype" | tr '[:lower:]' '[:upper:]')"
  local val="${!env_key:-}"
  if [[ -z "$val" && -n "${CONFIG_FILE:-}" ]]; then
    val=$(awk -v arch="$archetype" '
      /^  baselines:/ { in_baselines=1; next }
      in_baselines && /^  [^ ]/ { exit }
      in_baselines && $0 ~ "^    " arch ":" {
        gsub(/.*\[/, ""); gsub(/\].*/, ""); gsub(/ /, "");
        print; exit
      }
    ' "$CONFIG_FILE")
  else
    # Resolver wraps arrays as JSON: '[0.3,0.7,...]' — strip brackets for compat
    val=$(echo "$val" | tr -d '[]"' | tr ',' ',')
  fi
  echo "$val"
}

# Get adrenaline baseline (index 0) for an archetype
get_adrenaline_baseline() {
  local archetype="$1"
  local arr
  arr=$(get_baseline "$archetype")
  echo "$arr" | cut -d',' -f1
}

# Get baseline for a specific hormone index
get_hormone_baseline() {
  local archetype="$1" idx="$2"
  local arr
  arr=$(get_baseline "$archetype")
  echo "$arr" | cut -d',' -f$((idx + 1))
}

# ---------------------------------------------------------------------------
# Agent → archetype mapping
# ---------------------------------------------------------------------------

agent_to_archetype() {
  local agent="$1"
  case "$agent" in
    SCOUT|SYNTHESIZER|CARTOGRAPHER|MODELER|GOLDDIGGER|ANALYZER|SPECIFIER|EXPANDER)
      echo "exploration" ;;
    SAGE|VALIDATOR|CHECKPOINT|GUARDIAN|CHECKLISTER|VERIFIER)
      echo "validation" ;;
    GATEKEEPER)
      echo "feasibility" ;;
    ARCHITECT|ORCHESTRATOR|SENTINEL|ORACLE|BENCHMARK|PLANNER|TASKER)
      echo "solution" ;;
    IMPLEMENTER|SPEC_GUARD|CODE_REVIEWER|TEST_GUARDIAN|DEBUGGER|INTEGRATOR|CHANGE_CONTROLLER|VISUAL_VALIDATOR|VERIFICATION|ENGINEERING_MANAGER|IMPLEMENTATION_MAPPER|SPEC_FULFILLMENT_AUDITOR|TECH_WRITER|DOCS_VERIFIER)
      echo "build" ;;
    MAVERICK|INVESTIGATOR|ADVOCATE)
      echo "innovation" ;;
    MIRROR|ADAPTIVE|AUDITOR|INTERNALIZER|REALIST|CONSOLIDATOR|VETERAN|MONITOR)
      echo "learning" ;;
    COMMANDER|SCOREKEEPER|TRACKER|STRATEGIST|PROGRESS_TRACKER|CHIEF|CONSTITUTER)
      echo "control" ;;
    *)
      echo "control" ;;  # default fallback
  esac
}

# Known agents list
ALL_AGENTS=(
  COMMANDER SCOUT SYNTHESIZER SAGE CARTOGRAPHER MODELER
  VALIDATOR CHECKPOINT GATEKEEPER
  ARCHITECT ORCHESTRATOR SENTINEL
  IMPLEMENTER SPEC_GUARD CODE_REVIEWER TEST_GUARDIAN DEBUGGER INTEGRATOR CHANGE_CONTROLLER
  VISUAL_VALIDATOR VERIFICATION ENGINEERING_MANAGER
  MAVERICK INVESTIGATOR
  MIRROR ADAPTIVE AUDITOR INTERNALIZER REALIST CONSOLIDATOR
  SCOREKEEPER TRACKER STRATEGIST PROGRESS_TRACKER VETERAN
  GUARDIAN ORACLE BENCHMARK ADVOCATE GOLDDIGGER MONITOR
  CHIEF IMPLEMENTATION_MAPPER SPEC_FULFILLMENT_AUDITOR TECH_WRITER DOCS_VERIFIER
  ANALYZER SPECIFIER EXPANDER CONSTITUTER PLANNER TASKER CHECKLISTER VERIFIER
)

# ---------------------------------------------------------------------------
# State manipulation
# ---------------------------------------------------------------------------

ensure_state_file() {
  mkdir -p "$SQUAD_DIR"
  if [[ ! -s "$STATE_FILE" ]]; then
    echo '{}' > "$STATE_FILE"
  fi
}

# Read endocrine state for an agent from state.json
read_agent_state() {
  local agent="$1"
  require_jq
  jq -r ".endocrine_state.agents.\"$agent\" // empty" "$STATE_FILE"
}

# ---------------------------------------------------------------------------
# Generic hormone read/write helpers (used by Phase 2+ commands)
# ---------------------------------------------------------------------------

read_hormone_value() {
  local agent="$1" hormone_name="$2"
  require_jq
  local val
  val=$(jq -r ".endocrine_state.agents.\"$agent\".hormones.\"$hormone_name\" // empty" "$STATE_FILE")
  if [[ -z "$val" ]]; then
    echo "ERROR: agent $agent or hormone $hormone_name not found in endocrine state" >&2
    return 1
  fi
  echo "$val"
}

write_hormone_value() {
  local agent="$1" hormone_name="$2" value="$3"
  require_jq
  local now
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local updated
  updated=$(jq \
    --arg a "$agent" \
    --arg h "$hormone_name" \
    --argjson v "$value" \
    --arg ts "$now" \
    '.endocrine_state.agents[$a].hormones[$h] = $v |
     .endocrine_state.agents[$a].last_updated = $ts' "$STATE_FILE")
  echo "$updated" > "$STATE_FILE"
}

clamp_value() {
  local value="$1" floor="$2" ceiling="$3"
  awk -v v="$value" -v lo="$floor" -v hi="$ceiling" \
    'BEGIN { if (v < lo) print lo; else if (v > hi) print hi; else printf "%.2f", v }' | sed 's/0*$//' | sed 's/\.$//'
}

# ---------------------------------------------------------------------------
# Commands — Phase 1 (adrenaline)
# ---------------------------------------------------------------------------

cmd_init() {
  require_jq
  ensure_state_file

  local now
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # Build the endocrine_state object with all agents
  local agents_json="{}"
  for agent in "${ALL_AGENTS[@]}"; do
    local archetype
    archetype=$(agent_to_archetype "$agent")
    local baseline_csv
    baseline_csv=$(get_baseline "$archetype")
    # Parse the 6 hormone values
    local adr dop cor ser oxy nor
    adr=$(echo "$baseline_csv" | cut -d',' -f1)
    dop=$(echo "$baseline_csv" | cut -d',' -f2)
    cor=$(echo "$baseline_csv" | cut -d',' -f3)
    ser=$(echo "$baseline_csv" | cut -d',' -f4)
    oxy=$(echo "$baseline_csv" | cut -d',' -f5)
    nor=$(echo "$baseline_csv" | cut -d',' -f6)

    agents_json=$(echo "$agents_json" | jq \
      --arg a "$agent" \
      --arg arch "$archetype" \
      --argjson adr "${adr:-0.5}" \
      --argjson dop "${dop:-0.5}" \
      --argjson cor "${cor:-0.5}" \
      --argjson ser "${ser:-0.5}" \
      --argjson oxy "${oxy:-0.5}" \
      --argjson nor "${nor:-0.5}" \
      --arg ts "$now" \
      '.[$a] = {
        archetype: $arch,
        hormones: {
          adrenaline: $adr,
          dopamine: $dop,
          cortisol: $cor,
          serotonin: $ser,
          oxytocin: $oxy,
          norepinephrine: $nor
        },
        consecutive_extreme: 0,
        last_updated: $ts
      }')
  done

  # Merge into state.json
  local endocrine_obj
  endocrine_obj=$(jq -n \
    --argjson agents "$agents_json" \
    --arg ts "$now" \
    '{
      initialized: true,
      initialized_at: $ts,
      agents: $agents,
      trust_matrix: {},
      hormone_history: []
    }')

  local updated
  updated=$(jq --argjson endo "$endocrine_obj" '.endocrine_state = $endo' "$STATE_FILE")
  echo "$updated" > "$STATE_FILE"

  echo "OK: endocrine state initialized for ${#ALL_AGENTS[@]} agents"
}

cmd_get_adrenaline() {
  local agent="${1:?Usage: endocrine.sh get_adrenaline <agent>}"
  require_jq
  local val
  val=$(jq -r ".endocrine_state.agents.\"$agent\".hormones.adrenaline // empty" "$STATE_FILE")
  if [[ -z "$val" ]]; then
    echo "ERROR: agent $agent not found in endocrine state" >&2
    return 1
  fi
  echo "$val"
}

cmd_get_archetype() {
  local agent="${1:?Usage: endocrine.sh get_archetype <agent>}"
  agent_to_archetype "$agent"
}

cmd_set_adrenaline() {
  local agent="${1:?Usage: endocrine.sh set_adrenaline <agent> <value>}"
  local value="${2:?Usage: endocrine.sh set_adrenaline <agent> <value>}"
  require_jq

  local ceiling floor
  ceiling=$(get_ceiling)
  floor=$(get_floor)
  ceiling="${ceiling:-1.0}"
  floor="${floor:-0.0}"

  # Clamp value
  local clamped
  clamped=$(clamp_value "$value" "$floor" "$ceiling")

  local now
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local updated
  updated=$(jq \
    --arg a "$agent" \
    --argjson v "$clamped" \
    --arg ts "$now" \
    '.endocrine_state.agents[$a].hormones.adrenaline = $v |
     .endocrine_state.agents[$a].last_updated = $ts' "$STATE_FILE")
  echo "$updated" > "$STATE_FILE"

  echo "$clamped"
}

cmd_update_adrenaline() {
  local agent="${1:?Usage: endocrine.sh update_adrenaline <agent> <delta>}"
  local delta="${2:?Usage: endocrine.sh update_adrenaline <agent> <delta>}"
  require_jq

  local current
  current=$(cmd_get_adrenaline "$agent") || return 1

  local max_change
  max_change=$(get_max_change)
  max_change="${max_change:-0.3}"

  # Dampen delta to max_change_per_cycle
  local dampened
  dampened=$(awk -v d="$delta" -v m="$max_change" \
    'BEGIN {
      ad = (d < 0) ? -d : d;
      if (ad > m) { d = (d < 0) ? -m : m }
      print d
    }')

  local new_val
  new_val=$(awk -v c="$current" -v d="$dampened" 'BEGIN { printf "%.2f", c + d }' | sed 's/0*$//' | sed 's/\.$//')

  cmd_set_adrenaline "$agent" "$new_val"
}

cmd_decay_hormones() {
  local agent="${1:?Usage: endocrine.sh decay_hormones <agent>}"
  require_jq

  local archetype
  archetype=$(jq -r ".endocrine_state.agents.\"$agent\".archetype // empty" "$STATE_FILE")
  if [[ -z "$archetype" ]]; then
    echo "ERROR: agent $agent not found in endocrine state" >&2
    return 1
  fi

  local baseline_csv
  baseline_csv=$(get_baseline "$archetype")
  local adr_baseline
  adr_baseline=$(echo "$baseline_csv" | cut -d',' -f1)
  adr_baseline="${adr_baseline:-0.5}"

  local decay_rate
  decay_rate=$(get_decay_rate "adrenaline")
  decay_rate="${decay_rate:-0.7}"

  local current
  current=$(jq -r ".endocrine_state.agents.\"$agent\".hormones.adrenaline" "$STATE_FILE")

  # Exponential decay toward baseline: new = baseline + (current - baseline) * decay_rate
  local new_val
  new_val=$(awk -v c="$current" -v b="$adr_baseline" -v r="$decay_rate" \
    'BEGIN { printf "%.2f", b + (c - b) * r }' | sed 's/0*$//' | sed 's/\.$//')

  local now
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local updated
  updated=$(jq \
    --arg a "$agent" \
    --argjson v "$new_val" \
    --arg ts "$now" \
    '.endocrine_state.agents[$a].hormones.adrenaline = $v |
     .endocrine_state.agents[$a].last_updated = $ts' "$STATE_FILE")
  echo "$updated" > "$STATE_FILE"

  echo "$new_val"
}

cmd_check_circuit_breakers() {
  local agent="${1:?Usage: endocrine.sh check_circuit_breakers <agent>}"
  require_jq

  local ceiling floor max_consecutive
  ceiling=$(get_ceiling)
  floor=$(get_floor)
  max_consecutive=$(get_consecutive_extreme_reset)
  ceiling="${ceiling:-1.0}"
  floor="${floor:-0.0}"
  max_consecutive="${max_consecutive:-3}"

  local current consecutive archetype
  current=$(jq -r ".endocrine_state.agents.\"$agent\".hormones.adrenaline" "$STATE_FILE")
  consecutive=$(jq -r ".endocrine_state.agents.\"$agent\".consecutive_extreme // 0" "$STATE_FILE")
  archetype=$(jq -r ".endocrine_state.agents.\"$agent\".archetype // \"control\"" "$STATE_FILE")

  local at_extreme="false"
  at_extreme=$(awk -v c="$current" -v hi="$ceiling" -v lo="$floor" \
    'BEGIN { print (c >= hi || c <= lo) ? "true" : "false" }')

  local result="OK"

  if [[ "$at_extreme" == "true" ]]; then
    consecutive=$((consecutive + 1))
    if [[ "$consecutive" -ge "$max_consecutive" ]]; then
      # Reset to baseline
      local baseline_csv adr_baseline
      baseline_csv=$(get_baseline "$archetype")
      adr_baseline=$(echo "$baseline_csv" | cut -d',' -f1)
      adr_baseline="${adr_baseline:-0.5}"

      local now
      now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

      local updated
      updated=$(jq \
        --arg a "$agent" \
        --argjson v "$adr_baseline" \
        --arg ts "$now" \
        '.endocrine_state.agents[$a].hormones.adrenaline = $v |
         .endocrine_state.agents[$a].consecutive_extreme = 0 |
         .endocrine_state.agents[$a].last_updated = $ts' "$STATE_FILE")
      echo "$updated" > "$STATE_FILE"
      result="RESET: agent $agent reset to baseline $adr_baseline after $consecutive consecutive extreme cycles"
    else
      local updated
      updated=$(jq \
        --arg a "$agent" \
        --argjson c "$consecutive" \
        '.endocrine_state.agents[$a].consecutive_extreme = $c' "$STATE_FILE")
      echo "$updated" > "$STATE_FILE"
      result="WARNING: agent $agent at extreme ($current), consecutive=$consecutive/$max_consecutive"
    fi
  else
    # Reset consecutive counter if not at extreme
    if [[ "$consecutive" -gt 0 ]]; then
      local updated
      updated=$(jq \
        --arg a "$agent" \
        '.endocrine_state.agents[$a].consecutive_extreme = 0' "$STATE_FILE")
      echo "$updated" > "$STATE_FILE"
    fi
    result="OK"
  fi

  echo "$result"
}

cmd_get_prompt_modifier() {
  local agent="${1:?Usage: endocrine.sh get_prompt_modifier <agent>}"
  require_jq

  local adr
  adr=$(cmd_get_adrenaline "$agent") || return 1

  # Map adrenaline level to prompt modifier text (0.0-1.0 range)
  # Low [0.0, 0.3): calm, thorough exploration mode
  # Medium [0.3, 0.65): balanced, normal operation
  # High [0.65, 0.85): urgent, prioritize efficiency
  # Critical [0.85, 1.0]: emergency, maximum focus on completion

  local level
  level=$(awk -v a="$adr" 'BEGIN {
    if (a < 0.3) print "low"
    else if (a < 0.65) print "medium"
    else if (a < 0.85) print "high"
    else print "critical"
  }')

  case "$level" in
    low)
      cat <<'PROMPT'
[ENDOCRINE: adrenaline=LOW] You have ample time and budget. Prioritize thoroughness and exploration. Consider edge cases. Take the careful path.
PROMPT
      ;;
    medium)
      cat <<'PROMPT'
[ENDOCRINE: adrenaline=MEDIUM] Normal operating conditions. Balance thoroughness with efficiency. Standard quality expectations apply.
PROMPT
      ;;
    high)
      cat <<'PROMPT'
[ENDOCRINE: adrenaline=HIGH] Budget pressure detected. Prioritize efficiency over exploration. Focus on the most impactful work. Reduce verbose analysis — be concise and action-oriented.
PROMPT
      ;;
    critical)
      cat <<'PROMPT'
[ENDOCRINE: adrenaline=CRITICAL] Emergency mode. Budget nearly exhausted. Produce minimal viable output immediately. Skip nice-to-haves. Every token counts. Finish NOW.
PROMPT
      ;;
  esac
}

cmd_broadcast_adrenaline() {
  local delta="${1:?Usage: endocrine.sh broadcast_adrenaline <delta>}"
  require_jq

  local agents
  agents=$(jq -r '.endocrine_state.agents | keys[]' "$STATE_FILE" 2>/dev/null)
  if [[ -z "$agents" ]]; then
    echo "ERROR: no agents in endocrine state" >&2
    return 1
  fi

  local count=0
  while IFS= read -r agent; do
    cmd_update_adrenaline "$agent" "$delta" >/dev/null
    count=$((count + 1))
  done <<< "$agents"

  echo "OK: broadcast adrenaline delta=$delta to $count agents"
}

# ---------------------------------------------------------------------------
# Commands — Phase 2 (dopamine, cortisol, norepinephrine)
# ---------------------------------------------------------------------------

cmd_get_hormone() {
  local agent="${1:?Usage: endocrine.sh get_hormone <agent> <hormone_index>}"
  local idx="${2:?Usage: endocrine.sh get_hormone <agent> <hormone_index>}"
  local hname
  hname=$(hormone_name_by_index "$idx") || return 1
  read_hormone_value "$agent" "$hname"
}

cmd_set_hormone() {
  local agent="${1:?Usage: endocrine.sh set_hormone <agent> <hormone_index> <value>}"
  local idx="${2:?Usage: endocrine.sh set_hormone <agent> <hormone_index> <value>}"
  local value="${3:?Usage: endocrine.sh set_hormone <agent> <hormone_index> <value>}"
  require_jq

  local hname
  hname=$(hormone_name_by_index "$idx") || return 1

  local ceiling floor
  ceiling=$(get_ceiling)
  floor=$(get_floor)
  ceiling="${ceiling:-1.0}"
  floor="${floor:-0.0}"

  local clamped
  clamped=$(clamp_value "$value" "$floor" "$ceiling")

  write_hormone_value "$agent" "$hname" "$clamped"
  echo "$clamped"
}

cmd_update_hormone() {
  local agent="${1:?Usage: endocrine.sh update_hormone <agent> <hormone_index> <delta>}"
  local idx="${2:?Usage: endocrine.sh update_hormone <agent> <hormone_index> <delta>}"
  local delta="${3:?Usage: endocrine.sh update_hormone <agent> <hormone_index> <delta>}"
  require_jq

  local hname
  hname=$(hormone_name_by_index "$idx") || return 1

  local current
  current=$(read_hormone_value "$agent" "$hname") || return 1

  local max_change
  max_change=$(get_max_change)
  max_change="${max_change:-0.3}"

  # Dampen delta to max_change_per_cycle
  local dampened
  dampened=$(awk -v d="$delta" -v m="$max_change" \
    'BEGIN {
      ad = (d < 0) ? -d : d;
      if (ad > m) { d = (d < 0) ? -m : m }
      print d
    }')

  local new_val
  new_val=$(awk -v c="$current" -v d="$dampened" 'BEGIN { printf "%.2f", c + d }' | sed 's/0*$//' | sed 's/\.$//')

  cmd_set_hormone "$agent" "$idx" "$new_val"
}

cmd_on_gate_pass() {
  local agent="${1:?Usage: endocrine.sh on_gate_pass <agent>}"
  # dopamine (index 1) +0.15
  cmd_update_hormone "$agent" 1 0.15
}

cmd_on_gate_fail() {
  local agent="${1:?Usage: endocrine.sh on_gate_fail <agent>}"
  # dopamine (index 1) -0.20
  cmd_update_hormone "$agent" 1 -0.20 >/dev/null
  # cortisol (index 2) +0.10
  cmd_update_hormone "$agent" 2 0.10
}

cmd_on_rework() {
  local agent="${1:?Usage: endocrine.sh on_rework <agent>}"
  # cortisol (index 2) +0.10
  cmd_update_hormone "$agent" 2 0.10
}

cmd_on_low_confidence() {
  local agent="${1:?Usage: endocrine.sh on_low_confidence <agent>}"
  # cortisol (index 2) +0.20
  cmd_update_hormone "$agent" 2 0.20
}

cmd_on_innovate_summon() {
  # norepinephrine (index 5) -0.20 for MAVERICK
  cmd_update_hormone "MAVERICK" 5 -0.20
}

# ---------------------------------------------------------------------------
# Commands — Phase 3 (serotonin, oxytocin, inter-agent propagation)
# ---------------------------------------------------------------------------

cmd_on_quality_improvement() {
  # serotonin (index 3) +0.10 system-wide
  require_jq
  local agents
  agents=$(jq -r '.endocrine_state.agents | keys[]' "$STATE_FILE" 2>/dev/null)
  if [[ -z "$agents" ]]; then
    echo "ERROR: no agents in endocrine state" >&2
    return 1
  fi
  local count=0
  while IFS= read -r agent; do
    cmd_update_hormone "$agent" 3 0.10 >/dev/null
    count=$((count + 1))
  done <<< "$agents"
  echo "OK: serotonin +0.10 broadcast to $count agents"
}

cmd_on_quality_regression() {
  # serotonin (index 3) -0.15 system-wide
  require_jq
  local agents
  agents=$(jq -r '.endocrine_state.agents | keys[]' "$STATE_FILE" 2>/dev/null)
  if [[ -z "$agents" ]]; then
    echo "ERROR: no agents in endocrine state" >&2
    return 1
  fi
  local count=0
  while IFS= read -r agent; do
    cmd_update_hormone "$agent" 3 -0.15 >/dev/null
    count=$((count + 1))
  done <<< "$agents"
  echo "OK: serotonin -0.15 broadcast to $count agents"
}

cmd_on_peer_accept() {
  local from="${1:?Usage: endocrine.sh on_peer_accept <from_agent> <to_agent>}"
  local to="${2:?Usage: endocrine.sh on_peer_accept <from_agent> <to_agent>}"
  require_jq
  # oxytocin (index 4) +0.05 for both agents
  cmd_update_hormone "$from" 4 0.05 >/dev/null
  cmd_update_hormone "$to" 4 0.05 >/dev/null
  # Update trust matrix
  local trust_key="${from}_${to}"
  local current_trust
  current_trust=$(jq -r ".endocrine_state.trust_matrix.\"$trust_key\" // 0.5" "$STATE_FILE")
  local new_trust
  new_trust=$(awk -v t="$current_trust" 'BEGIN { v = t + 0.05; if (v > 1.0) v = 1.0; printf "%.2f", v }' | sed 's/0*$//' | sed 's/\.$//')
  local updated
  updated=$(jq \
    --arg k "$trust_key" \
    --argjson v "$new_trust" \
    '.endocrine_state.trust_matrix[$k] = $v' "$STATE_FILE")
  echo "$updated" > "$STATE_FILE"
  echo "OK: peer_accept $from->$to, trust=$new_trust"
}

cmd_on_peer_reject() {
  local from="${1:?Usage: endocrine.sh on_peer_reject <from_agent> <to_agent>}"
  local to="${2:?Usage: endocrine.sh on_peer_reject <from_agent> <to_agent>}"
  require_jq
  # oxytocin (index 4) -0.10 for both agents
  cmd_update_hormone "$from" 4 -0.10 >/dev/null
  cmd_update_hormone "$to" 4 -0.10 >/dev/null
  # Update trust matrix
  local trust_key="${from}_${to}"
  local current_trust
  current_trust=$(jq -r ".endocrine_state.trust_matrix.\"$trust_key\" // 0.5" "$STATE_FILE")
  local new_trust
  new_trust=$(awk -v t="$current_trust" 'BEGIN { v = t - 0.10; if (v < 0.0) v = 0.0; printf "%.2f", v }' | sed 's/0*$//' | sed 's/\.$//')
  local updated
  updated=$(jq \
    --arg k "$trust_key" \
    --argjson v "$new_trust" \
    '.endocrine_state.trust_matrix[$k] = $v' "$STATE_FILE")
  echo "$updated" > "$STATE_FILE"
  echo "OK: peer_reject $from->$to, trust=$new_trust"
}

cmd_propagate_downstream() {
  local from="${1:?Usage: endocrine.sh propagate_downstream <from_agent> <to_agent>}"
  local to="${2:?Usage: endocrine.sh propagate_downstream <from_agent> <to_agent>}"
  require_jq
  # Propagate dopamine at 30% strength: to.dopamine += (from.dopamine - 0.5) * 0.3
  local from_dop
  from_dop=$(read_hormone_value "$from" "dopamine") || return 1
  local delta
  delta=$(awk -v d="$from_dop" 'BEGIN { printf "%.2f", (d - 0.5) * 0.3 }' | sed 's/0*$//' | sed 's/\.$//')
  if [[ "$delta" != "0" && "$delta" != "0.0" && "$delta" != "0.00" ]]; then
    cmd_update_hormone "$to" 1 "$delta" >/dev/null
  fi
  echo "OK: propagated dopamine from $from ($from_dop) to $to, delta=$delta"
}

cmd_propagate_cortisol_contagion() {
  local from="${1:?Usage: endocrine.sh propagate_cortisol_contagion <from_agent> <to_agent>}"
  local to="${2:?Usage: endocrine.sh propagate_cortisol_contagion <from_agent> <to_agent>}"
  require_jq
  # If from.cortisol > 0.8, add +0.05 to target
  local from_cor
  from_cor=$(read_hormone_value "$from" "cortisol") || return 1
  local should_propagate
  should_propagate=$(awk -v c="$from_cor" 'BEGIN { print (c > 0.8) ? "yes" : "no" }')
  if [[ "$should_propagate" == "yes" ]]; then
    cmd_update_hormone "$to" 2 0.05 >/dev/null
    echo "OK: cortisol contagion from $from ($from_cor) to $to, +0.05"
  else
    echo "OK: no contagion, $from cortisol=$from_cor (<=0.8)"
  fi
}

cmd_get_trust() {
  local from="${1:?Usage: endocrine.sh get_trust <from_agent> <to_agent>}"
  local to="${2:?Usage: endocrine.sh get_trust <from_agent> <to_agent>}"
  require_jq
  local trust_key="${from}_${to}"
  local val
  val=$(jq -r ".endocrine_state.trust_matrix.\"$trust_key\" // 0.5" "$STATE_FILE")
  echo "$val"
}

cmd_get_full_prompt_modifier() {
  local agent="${1:?Usage: endocrine.sh get_full_prompt_modifier <agent>}"
  require_jq

  # Read all 6 hormone values
  local adr dop cor ser oxy nor
  adr=$(read_hormone_value "$agent" "adrenaline")     || return 1
  dop=$(read_hormone_value "$agent" "dopamine")       || return 1
  cor=$(read_hormone_value "$agent" "cortisol")       || return 1
  ser=$(read_hormone_value "$agent" "serotonin")      || return 1
  oxy=$(read_hormone_value "$agent" "oxytocin")       || return 1
  nor=$(read_hormone_value "$agent" "norepinephrine") || return 1

  # Classify each hormone: LOW <= 0.25, MEDIUM (0.25, 0.75), HIGH >= 0.75
  # (Spec section 2 levels.)
  classify() {
    awk -v v="$1" 'BEGIN {
      if (v <= 0.25) print "low"
      else if (v >= 0.75) print "high"
      else print "medium"
    }'
  }

  local adr_lvl dop_lvl cor_lvl ser_lvl oxy_lvl nor_lvl
  adr_lvl=$(classify "$adr")
  dop_lvl=$(classify "$dop")
  cor_lvl=$(classify "$cor")
  ser_lvl=$(classify "$ser")
  oxy_lvl=$(classify "$oxy")
  nor_lvl=$(classify "$nor")

  local archetype
  archetype=$(agent_to_archetype "$agent")

  # Load summary + overlays from echelon-config.yml interpretations block.
  # Use python3 since yaml_get only handles flat top-level keys.
  # CFG_PATH precedence: env var override > extension source > deployed copy > bare.
  # Honours ENDOCRINE_CONFIG_FILE so tests can substitute a custom interpretations
  # block without modifying the project's echelon-config.yml.
  local CFG_PATH=""
  if [[ -n "${ENDOCRINE_CONFIG_FILE:-}" ]] && [[ -f "$ENDOCRINE_CONFIG_FILE" ]]; then
    CFG_PATH="$ENDOCRINE_CONFIG_FILE"
  elif [[ -f "$REPO_ROOT/extension/echelon-config.yml" ]]; then
    CFG_PATH="$REPO_ROOT/extension/echelon-config.yml"
  elif [[ -f "$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml" ]]; then
    CFG_PATH="$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml"
  elif [[ -f "$REPO_ROOT/echelon-config.yml" ]]; then
    CFG_PATH="$REPO_ROOT/echelon-config.yml"
  fi

  local INTERP_RAW=""
  if [[ -n "$CFG_PATH" ]] && command -v "$PYTHON" &>/dev/null; then
    INTERP_RAW=$("$PYTHON" - "$CFG_PATH" "$archetype" 2>/dev/null <<'PY'
import yaml, sys
cfg_path, archetype = sys.argv[1], sys.argv[2]
try:
    cfg = yaml.safe_load(open(cfg_path)) or {}
except Exception:
    sys.exit(0)
arch = cfg.get('endocrine', {}).get('interpretations', {}).get(archetype, {})
if not arch:
    sys.exit(0)
summary = (arch.get('summary') or '').strip()
overlays = arch.get('overlays', {}) or {}
print('---SUMMARY---')
print(summary)
print('---OVERLAYS---')
for k, v in overlays.items():
    print(f'{k}::{v}')
PY
)
  fi

  # If no interpretation block found, fall back to legacy single-line modifier.
  if [[ -z "$INTERP_RAW" ]]; then
    echo "[ENDOCRINE: all hormones MEDIUM] Normal operating conditions."
    return 0
  fi

  local SUMMARY OVERLAYS_BLOB
  SUMMARY=$(echo "$INTERP_RAW" | sed -n '/^---SUMMARY---$/,/^---OVERLAYS---$/p' | sed '1d;$d')
  OVERLAYS_BLOB=$(echo "$INTERP_RAW" | sed -n '/^---OVERLAYS---$/,$p' | tail -n +2)

  # Emit the multi-line block.
  fmt() { printf "%.2f" "$1" 2>/dev/null || echo "$1"; }
  local adr_u dop_u cor_u ser_u oxy_u nor_u
  adr_u=$(echo "$adr_lvl" | tr '[:lower:]' '[:upper:]')
  dop_u=$(echo "$dop_lvl" | tr '[:lower:]' '[:upper:]')
  cor_u=$(echo "$cor_lvl" | tr '[:lower:]' '[:upper:]')
  ser_u=$(echo "$ser_lvl" | tr '[:lower:]' '[:upper:]')
  oxy_u=$(echo "$oxy_lvl" | tr '[:lower:]' '[:upper:]')
  nor_u=$(echo "$nor_lvl" | tr '[:lower:]' '[:upper:]')

  printf '[ENDOCRINE — %s archetype]\n' "$archetype"
  printf '  adrenaline: %s (%s)   dopamine: %s (%s)\n' "$(fmt "$adr")" "$adr_u" "$(fmt "$dop")" "$dop_u"
  printf '  cortisol:   %s (%s)   serotonin: %s (%s)\n' "$(fmt "$cor")" "$cor_u" "$(fmt "$ser")" "$ser_u"
  printf '  oxytocin:   %s (%s)   norepinephrine: %s (%s)\n' "$(fmt "$oxy")" "$oxy_u" "$(fmt "$nor")" "$nor_u"
  printf '\n'
  printf 'Interpretation (%s archetype):\n' "$archetype"
  echo "$SUMMARY" | sed 's/^/  /'

  # Emit overlays for any hormone at HIGH/LOW that has a matching overlay.
  emit_overlay() {
    local hormone="$1" level="$2"
    local key="${hormone}_${level}"
    local val
    val=$(echo "$OVERLAYS_BLOB" | sed -n "s|^${key}::||p")
    if [[ -n "$val" ]]; then
      local level_uc
      level_uc=$(echo "$level" | tr '[:lower:]' '[:upper:]')
      printf '  - %s %s: %s\n' "$level_uc" "$hormone" "$val"
    fi
  }

  for pair in "adrenaline:$adr_lvl" "dopamine:$dop_lvl" "cortisol:$cor_lvl" \
              "serotonin:$ser_lvl" "oxytocin:$oxy_lvl" "norepinephrine:$nor_lvl"; do
    hormone="${pair%%:*}"
    level="${pair##*:}"
    [[ "$level" == "medium" ]] && continue
    emit_overlay "$hormone" "$level"
  done

  # Preserve the existing [CALIBRATION] suffix — commander.md §198 reads it
  # from this function's output and appends it to the agent's prompt. Removing
  # it would break the protocol. (Future refactor: deduplicate against
  # commander.md §175-190's own calibration injection — out of scope.)
  local SCORES_FILE="$REPO_ROOT/knowledge-base/agent-scores.yaml"
  if [[ -f "$SCORES_FILE" ]] && command -v "$PYTHON" &>/dev/null; then
    "$PYTHON" - "$SCORES_FILE" "$agent" 2>/dev/null <<'PY'
import yaml, sys
scores_path, agent = sys.argv[1], sys.argv[2]
try:
    with open(scores_path) as f:
        data = yaml.safe_load(f) or {}
    agents = data.get('agents', {})
    a = agents.get(agent, {})
    history = a.get('history', a.get('run_history', []))
    if not history:
        sys.exit(0)
    last = history[-1] if isinstance(history, list) else {}
    score = last.get('quality_score', last.get('score', '?'))
    modes = last.get('failure_modes', [])
    if modes:
        fm = modes[0]
        print(f'[CALIBRATION] Prior score: {score}. Miss: {fm.get("type","unknown")} ({fm.get("count","?")}x). Example: {fm.get("example","none")}')
    else:
        print(f'[CALIBRATION] Prior score: {score}. No failure modes recorded.')
except Exception as e:
    print(f'[CALIBRATION] COLD START — error reading scores: {e}')
PY
  fi
}

# ---------------------------------------------------------------------------
# Commands — Phase 4 (SCOREKEEPER correlation hooks)
# ---------------------------------------------------------------------------

cmd_get_hormone_snapshot() {
  local agent="${1:?Usage: endocrine.sh get_hormone_snapshot <agent>}"
  require_jq

  local adr dop cor ser oxy nor
  adr=$(read_hormone_value "$agent" "adrenaline") || return 1
  dop=$(read_hormone_value "$agent" "dopamine") || return 1
  cor=$(read_hormone_value "$agent" "cortisol") || return 1
  ser=$(read_hormone_value "$agent" "serotonin") || return 1
  oxy=$(read_hormone_value "$agent" "oxytocin") || return 1
  nor=$(read_hormone_value "$agent" "norepinephrine") || return 1

  echo "$adr,$dop,$cor,$ser,$oxy,$nor"
}

cmd_log_hormone_event() {
  local agent="${1:?Usage: endocrine.sh log_hormone_event <agent> <event_type>}"
  local event_type="${2:?Usage: endocrine.sh log_hormone_event <agent> <event_type>}"
  require_jq

  local snapshot
  snapshot=$(cmd_get_hormone_snapshot "$agent") || return 1

  local now
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local updated
  updated=$(jq \
    --arg a "$agent" \
    --arg ev "$event_type" \
    --arg snap "$snapshot" \
    --arg ts "$now" \
    '.endocrine_state.hormone_history += [{
      agent: $a,
      event_type: $ev,
      snapshot: $snap,
      timestamp: $ts
    }]' "$STATE_FILE")
  echo "$updated" > "$STATE_FILE"

  echo "OK: logged $event_type for $agent at $now"
}

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

usage() {
  cat >&2 <<'USAGE'
usage:
  endocrine.sh init
  endocrine.sh get_adrenaline <agent>
  endocrine.sh get_archetype <agent>
  endocrine.sh set_adrenaline <agent> <value>
  endocrine.sh update_adrenaline <agent> <delta>
  endocrine.sh decay_hormones <agent>
  endocrine.sh check_circuit_breakers <agent>
  endocrine.sh get_prompt_modifier <agent>
  endocrine.sh broadcast_adrenaline <delta>
  endocrine.sh get_hormone <agent> <index>
  endocrine.sh set_hormone <agent> <index> <value>
  endocrine.sh update_hormone <agent> <index> <delta>
  endocrine.sh on_gate_pass <agent>
  endocrine.sh on_gate_fail <agent>
  endocrine.sh on_rework <agent>
  endocrine.sh on_low_confidence <agent>
  endocrine.sh on_innovate_summon
  endocrine.sh on_quality_improvement
  endocrine.sh on_quality_regression
  endocrine.sh on_peer_accept <from> <to>
  endocrine.sh on_peer_reject <from> <to>
  endocrine.sh propagate_downstream <from> <to>
  endocrine.sh propagate_cortisol_contagion <from> <to>
  endocrine.sh get_trust <from> <to>
  endocrine.sh get_full_prompt_modifier <agent>
  endocrine.sh get_hormone_snapshot <agent>
  endocrine.sh log_hormone_event <agent> <event_type>
USAGE
  exit 1
}

cmd="${1:-}"
shift || true

# Enforce kill switch — if endocrine.enabled is explicitly false, no-op silently and exit.
# Default is enabled (opt-out model): endocrine runs unless echelon-config.yml sets enabled: false.
if [[ "$(get_enabled)" != "true" ]]; then
  exit 0
fi

case "$cmd" in
  init)                          cmd_init ;;
  get_adrenaline)                cmd_get_adrenaline "$@" ;;
  get_archetype)                 cmd_get_archetype "$@" ;;
  set_adrenaline)                cmd_set_adrenaline "$@" ;;
  update_adrenaline)             cmd_update_adrenaline "$@" ;;
  decay_hormones)                cmd_decay_hormones "$@" ;;
  check_circuit_breakers)        cmd_check_circuit_breakers "$@" ;;
  get_prompt_modifier)           cmd_get_prompt_modifier "$@" ;;
  broadcast_adrenaline)          cmd_broadcast_adrenaline "$@" ;;
  get_hormone)                   cmd_get_hormone "$@" ;;
  set_hormone)                   cmd_set_hormone "$@" ;;
  update_hormone)                cmd_update_hormone "$@" ;;
  on_gate_pass)                  cmd_on_gate_pass "$@" ;;
  on_gate_fail)                  cmd_on_gate_fail "$@" ;;
  on_rework)                     cmd_on_rework "$@" ;;
  on_low_confidence)             cmd_on_low_confidence "$@" ;;
  on_innovate_summon)            cmd_on_innovate_summon ;;
  on_quality_improvement)        cmd_on_quality_improvement ;;
  on_quality_regression)         cmd_on_quality_regression ;;
  on_peer_accept)                cmd_on_peer_accept "$@" ;;
  on_peer_reject)                cmd_on_peer_reject "$@" ;;
  propagate_downstream)          cmd_propagate_downstream "$@" ;;
  propagate_cortisol_contagion)  cmd_propagate_cortisol_contagion "$@" ;;
  get_trust)                     cmd_get_trust "$@" ;;
  get_full_prompt_modifier)      cmd_get_full_prompt_modifier "$@" ;;
  get_hormone_snapshot)          cmd_get_hormone_snapshot "$@" ;;
  log_hormone_event)             cmd_log_hormone_event "$@" ;;
  *)                             usage ;;
esac
