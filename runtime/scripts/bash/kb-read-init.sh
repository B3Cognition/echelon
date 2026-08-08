#!/usr/bin/env bash
# kb-read-init.sh — Emit the canonical init_knowledge_read journal entry as JSON.
#
# Replaces the model-driven init.md §0.1 read-attempt with a deterministic check.
# Prevents the BUG-1 failure mode (squad-1778936191) where COMMANDER fabricated
# "files_absent" entries for patterns.yaml / pitfalls.yaml / agent-scores.yaml
# without ever issuing a Read tool call.
#
# Usage:
#   bash kb-read-init.sh [--id RJ-NNN] [--agent NAME] [--phase PHASE]
#
# Output: one JSON object on stdout (the journal entry — caller appends to
#         the active run's reasoning-journal.jsonl with `>>`).
#
# Exit codes:
#   0 = success (cold-start and all-files-absent are valid states)
#   1 = no .specify/ found walking up from CWD

set -euo pipefail

ID="RJ-001"
AGENT="echelon.commander"
PHASE="init"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --id)    ID="$2";    shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --phase) PHASE="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "kb-read-init: unknown arg: $1" >&2; exit 1 ;;
  esac
done

# Walk up from CWD looking for .specify/ — anchors the project root deterministically.
ROOT="$(pwd)"
while [ "$ROOT" != "/" ] && [ ! -d "$ROOT/.specify" ]; do
  ROOT=$(dirname "$ROOT")
done
if [ "$ROOT" = "/" ]; then
  echo "kb-read-init: no .specify/ in CWD or any parent" >&2
  exit 1
fi
cd "$ROOT"

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Canonical set — also defined in workflow/phases/init.md §0.1 and commander.md §0.1.
KB_FILES=(
  "knowledge-base/calibration-profile.yaml"
  "knowledge-base/patterns.yaml"
  "knowledge-base/pitfalls.yaml"
  "knowledge-base/agent-scores.yaml"
)

READ_LIST=""
ABSENT_LIST=""
for f in "${KB_FILES[@]}"; do
  if [ -f "$f" ] && [ -r "$f" ]; then
    READ_LIST="${READ_LIST}${READ_LIST:+|}${f}"
  else
    ABSENT_LIST="${ABSENT_LIST}${ABSENT_LIST:+|}${f}"
  fi
done

# Cold-start: feedback dir is absent OR contains fewer than 3 files
# (matches commander.md §0.1 cold_start detection rule).
COLD_START=true
if [ -d "knowledge-base/feedback" ]; then
  FB_COUNT=$(ls -1 knowledge-base/feedback 2>/dev/null | wc -l)
  if [ "$FB_COUNT" -ge 3 ]; then
    COLD_START=false
  fi
fi

# calibration_map size: number of agents in agent-scores.yaml that have history
CAL_COUNT=0
if [ -f knowledge-base/agent-scores.yaml ] && command -v python3 >/dev/null 2>&1; then
  CAL_COUNT=$(python3 - <<'PY' 2>/dev/null || echo 0
import yaml
try:
    data = yaml.safe_load(open('knowledge-base/agent-scores.yaml')) or {}
except Exception:
    print(0); raise SystemExit(0)
agents = data.get('agents', data)
if isinstance(agents, dict):
    n = sum(
        1 for v in agents.values()
        if isinstance(v, dict) and (v.get('history') or v.get('run_history'))
    )
    print(n)
else:
    print(0)
PY
)
fi

# Emit canonical JSON (one line, ready for `>> reasoning-journal.jsonl`).
ID="$ID" AGENT="$AGENT" PHASE="$PHASE" NOW="$NOW" \
READ_FILES="$READ_LIST" ABSENT_FILES="$ABSENT_LIST" \
COLD_START="$COLD_START" CAL_COUNT="$CAL_COUNT" \
python3 - <<'PY'
import json, os

read_csv = os.environ["READ_FILES"]
absent_csv = os.environ["ABSENT_FILES"]

entry = {
    "id": os.environ["ID"],
    "type": "init_knowledge_read",
    "agent": os.environ["AGENT"],
    "phase": os.environ["PHASE"],
    "timestamp": os.environ["NOW"],
    "files_read": read_csv.split("|") if read_csv else [],
    "files_absent": absent_csv.split("|") if absent_csv else [],
    "cold_start": os.environ["COLD_START"] == "true",
    "calibration_map_agents_loaded": int(os.environ["CAL_COUNT"]),
    "source": "kb-read-init.sh",
}
print(json.dumps(entry, separators=(",", ":")))
PY
