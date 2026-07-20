#!/usr/bin/env bash
# Integration: phase timing stays append-only across multiple phases.
set -euo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

tmpdir="$(mktemp -d)"
run_dir="$tmpdir/runs/spec-1"
state_file="$run_dir/state.json"
mkdir -p "$run_dir"
printf '{"phase":"phase1-understand","run_id":"spec-1"}\n' > "$state_file"

$PYTHON - "$run_dir" <<'PY'
import sys
from pathlib import Path
from echelon.telemetry.store import TelemetryStore

TelemetryStore(
    Path(sys.argv[1]), workflow="spec", run_id="spec-1",
    profile={"name": "banzai"}, trace_id="a" * 32,
).ensure_manifest()
PY

for phase_budget in "phase1-understand:2400" "phase2-decide:1800" "phase3-solution:2400"; do
  phase="${phase_budget%%:*}"
  budget="${phase_budget##*:}"
  bash "$SCRIPTS/phase-timing.sh" start_phase "$phase" "$budget" --state-file "$state_file"
  sleep 1
  bash "$SCRIPTS/phase-timing.sh" end_phase "$phase" --state-file "$state_file"
done

$PYTHON - "$run_dir/telemetry/events.jsonl" "$state_file" <<'PY'
import json
import sys
from pathlib import Path

events = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
state = json.loads(Path(sys.argv[2]).read_text())
for phase in ("phase1-understand", "phase2-decide", "phase3-solution"):
    records = [event for event in events if event.get("type") == "phase_timing" and event.get("phase") == phase]
    assert [record.get("event") for record in records] == ["started", "finished"], records
    assert records[-1]["elapsed_seconds"] >= 1, records[-1]
assert "phase_timings" not in state
print("timing event-stream linkage checks: PASS")
PY

rm -rf "$tmpdir"
