#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SCRIPT="$ROOT_DIR/extension/scripts/bash/phase-timing.sh"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

tmpdir="$(mktemp -d)"
run_dir="$tmpdir/runs/spec-1"
state_file="$run_dir/state.json"
mkdir -p "$run_dir"
printf '{"phase":"phase4-build","run_id":"spec-1"}\n' > "$state_file"

python3 - "$run_dir" <<'PY'
import sys
from pathlib import Path
from echelon.telemetry.store import TelemetryStore

TelemetryStore(Path(sys.argv[1]), workflow="spec", run_id="spec-1", profile={}, trace_id="a" * 32).ensure_manifest()
PY

bash "$SCRIPT" record_split_metrics 2 1 1.00 --state-file "$state_file"

python3 - "$run_dir" "$state_file" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
state = json.loads(Path(sys.argv[2]).read_text())
events = [json.loads(line) for line in (run_dir / "telemetry/events.jsonl").read_text().splitlines()]
assert "split_metrics" not in state
assert events[-1]["type"] == "split_metrics"
assert events[-1]["qa_coverage"] == 1.0
PY

rm -rf "$tmpdir"
echo "build-qa metrics event checks: PASS"
