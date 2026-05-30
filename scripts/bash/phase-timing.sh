#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"

# Detect the active spec run dir from runs/.current (primary); legacy squad/.current fallback.
_phase_timing_squad_dir() {
  local root="$1" base run_id current_file
  for base in runs squad; do
    current_file="$root/$base/.current"
    if [[ -f "$current_file" ]]; then
      run_id=$(tr -d '[:space:]' < "$current_file")
      if [[ -n "$run_id" && -d "$root/$base/$run_id" ]]; then
        echo "$root/$base/$run_id"; return 0
      fi
    fi
  done
  echo "$root/.specify/squad"
}
_SQUAD_DIR="$(_phase_timing_squad_dir "$REPO_ROOT")"
STATE_FILE_DEFAULT="$_SQUAD_DIR/state.json"
JOURNAL_FILE_DEFAULT="$_SQUAD_DIR/reasoning-journal.jsonl"

usage() {
  cat >&2 <<'USAGE'
usage:
  phase-timing.sh start_phase <phase_key> <budget_seconds> [--state-file <path>]
  phase-timing.sh end_phase <phase_key> [--state-file <path>] [--journal-file <path>] [--run-id <id>]
  phase-timing.sh record_split_metrics <rework_count> <fallback_count> <qa_coverage> [--state-file <path>]

split-phase aliases accepted for <phase_key>:
  BUILD_IN_PROGRESS | build -> phase4-build
  QA_IN_PROGRESS    | qa    -> phase5-qa
USAGE
}

record_split_metrics_cmd() {
  local rework_count="$1"
  local fallback_count="$2"
  local qa_coverage="$3"
  local state_file="$4"

  python3 - "$state_file" "$rework_count" "$fallback_count" "$qa_coverage" <<'PY'
import json
import os
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
rework = int(sys.argv[2])
fallback = int(sys.argv[3])
coverage = float(sys.argv[4])

if state_path.exists():
  try:
    data = json.loads(state_path.read_text(encoding="utf-8"))
  except Exception:
    data = {}
else:
  state_path.parent.mkdir(parents=True, exist_ok=True)
  data = {}

metrics = data.setdefault("split_metrics", {})
metrics["rework_count"] = rework
metrics["fallback_count"] = fallback
metrics["qa_coverage"] = coverage

tmp = state_path.with_name(state_path.name + f".tmp.{os.getpid()}")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp, state_path)
PY
}

normalize_phase_key() {
  local raw="$1"
  case "$raw" in
    BUILD_IN_PROGRESS|build)
      echo "phase4-build"
      ;;
    QA_IN_PROGRESS|qa)
      echo "phase5-qa"
      ;;
    *)
      echo "$raw"
      ;;
  esac
}

now_iso_utc() {
  python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
}

start_phase_cmd() {
  local phase_key="$1"
  phase_key="$(normalize_phase_key "$phase_key")"
  local budget_seconds="$2"
  local state_file="$3"

  python3 - "$state_file" "$phase_key" "$budget_seconds" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path = Path(sys.argv[1])
phase_key = sys.argv[2]
budget_seconds = float(sys.argv[3])
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

if state_path.exists():
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
else:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = {}

phase_timings = data.setdefault("phase_timings", {})
entry = phase_timings.setdefault(phase_key, {})
entry["start_ts"] = now
entry["budget_seconds"] = budget_seconds

out = json.dumps(data, indent=2, sort_keys=True) + "\n"
tmp = state_path.with_name(state_path.name + f".tmp.{os.getpid()}")
tmp.write_text(out, encoding="utf-8")
os.replace(tmp, state_path)
PY
}

append_timing_anomaly() {
  local journal_file="$1"
  local phase_key="$2"
  local run_id="$3"
  local elapsed_seconds="$4"
  local budget_seconds="$5"

  python3 - "$journal_file" "$phase_key" "$run_id" "$elapsed_seconds" "$budget_seconds" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

journal_path = Path(sys.argv[1])
phase_key = sys.argv[2]
run_id = sys.argv[3]
elapsed_seconds = float(sys.argv[4])
budget_seconds = float(sys.argv[5])
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

journal_path.parent.mkdir(parents=True, exist_ok=True)
entry = {
    "type": "timing_anomaly",
    "phase": phase_key,
    "run_id": run_id,
    "elapsed_seconds": elapsed_seconds,
    "budget_seconds": budget_seconds,
    "anomaly_reason": "EXCEEDED_BUDGET_20_PERCENT",
    "timestamp": now,
}
with journal_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(entry, sort_keys=True) + "\n")
PY
}

end_phase_cmd() {
  local phase_key="$1"
  phase_key="$(normalize_phase_key "$phase_key")"
  local state_file="$2"
  local journal_file="$3"
  local run_id="$4"

  local result
  result="$(python3 - "$state_file" "$phase_key" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path = Path(sys.argv[1])
phase_key = sys.argv[2]

if not state_path.exists():
    print("ERROR:STATE_FILE_MISSING")
    sys.exit(1)

try:
    data = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    print("ERROR:STATE_FILE_INVALID")
    sys.exit(1)

phase_timings = data.setdefault("phase_timings", {})
entry = phase_timings.get(phase_key)
if not entry or "start_ts" not in entry:
    print("ERROR:MISSING_START_TIMESTAMP")
    sys.exit(1)

start_ts = entry["start_ts"]
raw = start_ts[:-1] + "+00:00" if isinstance(start_ts, str) and start_ts.endswith("Z") else start_ts
start_dt = datetime.fromisoformat(raw)
if start_dt.tzinfo is None:
    start_dt = start_dt.replace(tzinfo=timezone.utc)

now_dt = datetime.now(timezone.utc)
now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
elapsed = (now_dt - start_dt).total_seconds()

budget = float(entry.get("budget_seconds", 0))
over_budget = elapsed > (budget * 1.2) if budget > 0 else False

entry["end_ts"] = now_iso
entry["elapsed_seconds"] = elapsed
entry["over_budget"] = over_budget
if over_budget:
    entry["anomaly_reason"] = "EXCEEDED_BUDGET_20_PERCENT"
else:
    entry["anomaly_reason"] = None

out = json.dumps(data, indent=2, sort_keys=True) + "\n"
tmp = state_path.with_name(state_path.name + f".tmp.{os.getpid()}")
tmp.write_text(out, encoding="utf-8")
os.replace(tmp, state_path)

print(f"{int(over_budget)}|{elapsed}|{budget}")
PY
)"

  if [[ "$result" == ERROR:* ]]; then
    printf '%s\n' "$result" >&2
    return 1
  fi

  local over_budget elapsed budget
  IFS='|' read -r over_budget elapsed budget <<< "$result"

  if [[ "$over_budget" == "1" ]]; then
    append_timing_anomaly "$journal_file" "$phase_key" "$run_id" "$elapsed" "$budget"
  fi
}

main() {
  if [[ $# -lt 2 ]]; then
    usage
    exit 64
  fi

  local command="$1"
  shift

  local phase_key="${1:-}"
  shift

  local budget_seconds=""
  local qa_coverage=""
  local state_file="$STATE_FILE_DEFAULT"
  local journal_file="$JOURNAL_FILE_DEFAULT"
  local run_id=""

  if [[ "$command" == "start_phase" ]]; then
    budget_seconds="${1:-}"
    shift
  elif [[ "$command" == "record_split_metrics" ]]; then
    budget_seconds="${1:-}"
    qa_coverage="${2:-}"
    shift 2
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --state-file)
        shift
        state_file="${1:-}"
        ;;
      --journal-file)
        shift
        journal_file="${1:-}"
        ;;
      --run-id)
        shift
        run_id="${1:-}"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        usage
        exit 64
        ;;
    esac
    shift
  done

  case "$command" in
    start_phase)
      if [[ -z "$phase_key" || -z "$budget_seconds" ]]; then
        usage
        exit 64
      fi
      start_phase_cmd "$phase_key" "$budget_seconds" "$state_file"
      ;;
    end_phase)
      if [[ -z "$phase_key" ]]; then
        usage
        exit 64
      fi
      if [[ -z "$run_id" ]]; then
        run_id="$(python3 - "$state_file" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    print("unknown-run")
    sys.exit(0)
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("unknown-run")
    sys.exit(0)
print(data.get("run_id", "unknown-run"))
PY
)"
      fi
      end_phase_cmd "$phase_key" "$state_file" "$journal_file" "$run_id"
      ;;
    record_split_metrics)
      if [[ -z "$phase_key" || -z "$budget_seconds" || -z "$qa_coverage" ]]; then
        usage
        exit 64
      fi
      local rework_count="$phase_key"
      local fallback_count="$budget_seconds"
      record_split_metrics_cmd "$rework_count" "$fallback_count" "$qa_coverage" "$state_file"
      ;;
    *)
      usage
      exit 64
      ;;
  esac
}

main "$@"
