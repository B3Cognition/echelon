#!/usr/bin/env bash
# Unit tests for the compatibility phase-timing shim.
set -euo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

pass=0
fail=0

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1))
    printf 'FAIL: %s — %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result() { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
run_dir="$tmpdir/runs/spec-1"
state_file="$run_dir/state.json"
mkdir -p "$run_dir"
original_state='{"phase":"phase2-decide","run_id":"spec-1"}'
printf '%s\n' "$original_state" > "$state_file"

$PYTHON - "$run_dir" <<'PY'
import sys
from pathlib import Path
from echelon.telemetry.store import TelemetryStore

run_dir = Path(sys.argv[1])
TelemetryStore(
    run_dir,
    workflow="spec",
    run_id="spec-1",
    profile={"name": "banzai"},
    trace_id="a" * 32,
).ensure_manifest()
PY

bash "$SCRIPTS/phase-timing.sh" start_phase "phase2-decide" 300 --state-file "$state_file"
sleep 1
bash "$SCRIPTS/phase-timing.sh" end_phase "phase2-decide" --state-file "$state_file"
bash "$SCRIPTS/phase-timing.sh" record_split_metrics 2 1 0.75 --state-file "$state_file"

assert "phase timing leaves controller state unchanged" "$(
  [[ "$(cat "$state_file")" == "$original_state" ]] && ok_result || fail_result "state mutated"
)"
assert "phase start and finish are append-only events" "$(
  $PYTHON - "$run_dir/telemetry/events.jsonl" <<'PY'
import json
import sys
events = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
phase_events = [event for event in events if event.get("type") == "phase_timing"]
print("OK" if [event.get("event") for event in phase_events] == ["started", "finished"] else f"FAIL:{phase_events}")
PY
)"
assert "finished event records elapsed duration" "$(
  $PYTHON - "$run_dir/telemetry/events.jsonl" <<'PY'
import json
import sys
events = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
finished = next(event for event in events if event.get("type") == "phase_timing" and event.get("event") == "finished")
print("OK" if float(finished["elapsed_seconds"]) >= 1 else f"FAIL:{finished}")
PY
)"
assert "split metrics are append-only events" "$(
  $PYTHON - "$run_dir/telemetry/events.jsonl" <<'PY'
import json
import sys
events = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
split = next((event for event in events if event.get("type") == "split_metrics"), None)
print("OK" if split and split.get("qa_coverage") == 0.75 else f"FAIL:{split}")
PY
)"

rm -rf "$tmpdir"
printf '\nResults: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
