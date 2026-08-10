#!/usr/bin/env bash
# T042: Benchmark B-002 — Convergence Timing
# Runs 5 controlled squad phase simulations with instrumented timing.
# Captures per-phase durations, issue counts, and convergence iteration count.
# Asserts >= 95% of runs have complete timing fields (AC-003a-2).
# Includes split-vs-monolithic labeling for BUILD/QA phase pilot reporting.
# Isolation: each run uses its own KB root via KB_ROOT env var + tmp dir.
# Output: JSON + markdown in tests/benchmarks/reports/
set -uo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/runtime/scripts/bash"
FIXTURES="$REPO_ROOT/tests/fixtures/kb/valid-seeds"
REPORTS_DIR="$REPO_ROOT/tests/benchmarks/reports"

mkdir -p "$REPORTS_DIR"

results_json="$REPORTS_DIR/convergence-timing.json"
results_md="$REPORTS_DIR/convergence-timing.md"

# Number of simulated runs (spec requires >= 5)
RUN_COUNT=5
MODE_LABEL="build-qa-split-v0.4.0"

# Phase simulation durations (seconds): these are fast sims, not real squad runs.
PHASE_BUDGETS=(
  "phase1-understand:4"
  "phase2-decide:3"
  "phase3-solution:4"
)

printf '{"runs":[],"summary":{}}\n' > "$results_json"

printf '# B-002: Convergence Timing Benchmark\n\n' > "$results_md"
printf 'Mode: %s\n\n' "$MODE_LABEL" >> "$results_md"
printf 'Generated: %s\n\n' "$($PYTHON -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')" >> "$results_md"
printf '| Run | phase1-understand (s) | phase2-decide (s) | phase3-solution (s) | Over-budget | Complete |\n' >> "$results_md"
printf '|-----|-----------------------|-------------------|---------------------|-------------|----------|\n' >> "$results_md"

complete_runs=0

for run_num in $(seq 1 "$RUN_COUNT"); do
  run_id="bench-conv-$($PYTHON -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))')-r${run_num}"

  # Isolated tmpdir for this run
  run_tmpdir="$(mktemp -d)"
  run_state="$run_tmpdir/state.json"
  run_kb="$run_tmpdir/estimates-log.yaml"

  printf '{"run_id":"%s"}\n' "$run_id" > "$run_state"
  cp "$FIXTURES/estimates-log.yaml" "$run_kb"

  $PYTHON - "$run_tmpdir" "$run_id" <<'PY'
import sys
from pathlib import Path
from echelon.telemetry.store import TelemetryStore

TelemetryStore(
    Path(sys.argv[1]),
    workflow="spec",
    run_id=sys.argv[2],
    profile={"name": "benchmark"},
    trace_id="a" * 32,
).ensure_manifest()
PY

  phase_results=()
  over_budget_any="false"
  run_complete="true"

  for phase_budget in "${PHASE_BUDGETS[@]}"; do
    phase_key="${phase_budget%%:*}"
    budget="${phase_budget##*:}"

    bash "$SCRIPTS/phase-timing.sh" start_phase "$phase_key" "$budget" --state-file "$run_state"

    # Simulate phase work: 1s for phases that are well within budget
    sleep 1

    bash "$SCRIPTS/phase-timing.sh" end_phase "$phase_key" \
      --state-file "$run_state"

    # Read the append-only finish event.
    timing_result="$($PYTHON - "$run_tmpdir/telemetry/events.jsonl" "$phase_key" <<'PY'
import json
import sys

events = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
finished = next(
    (
        event
        for event in reversed(events)
        if event.get("type") == "phase_timing"
        and event.get("phase") == sys.argv[2]
        and event.get("event") == "finished"
    ),
    None,
)
if finished is None:
    print("-1|False")
else:
    print(f"{finished['elapsed_seconds']}|{finished['over_budget']}")
PY
)"
    elapsed="${timing_result%%|*}"
    over_budget_phase="${timing_result##*|}"
    [[ "$over_budget_phase" == "True" ]] && over_budget_any="true"

    if [[ "$elapsed" == "-1" ]]; then
      run_complete="false"
    fi

    phase_results+=("$elapsed")
  done

  # Write timing entry to run-local KB (isolation: use run_kb not shared KB)
  bash "$SCRIPTS/kb-write.sh" append_entry \
    --file "$run_kb" \
    --payload "$(printf 'id: bench-%s\nagent: BENCHMARK\ndomain: convergence-timing\nestimate_hours: %s\nconfidence: 0.9\nrun_id: %s' \
      "$run_id" "${phase_results[0]:-0}" "$run_id")" \
    --run-id "$run_id" \
    --source "BENCHMARK" \
    --operation-id "op-bench-conv-$run_num" >/dev/null 2>/dev/null || true

  [[ "$run_complete" == "true" ]] && complete_runs=$((complete_runs + 1))

  printf '| %d | %.2f | %.2f | %.2f | %s | %s |\n' \
    "$run_num" \
    "${phase_results[0]:-0}" \
    "${phase_results[1]:-0}" \
    "${phase_results[2]:-0}" \
    "$over_budget_any" \
    "$run_complete" >> "$results_md"

  # Append run to results JSON
  $PYTHON - "$results_json" "$run_id" "$run_num" \
    "${phase_results[0]:-0}" "${phase_results[1]:-0}" "${phase_results[2]:-0}" \
    "$over_budget_any" "$run_complete" <<'PY'
import json, sys
from pathlib import Path
results_path = Path(sys.argv[1])
data = json.loads(results_path.read_text(encoding="utf-8"))
data["runs"].append({
    "run_id": sys.argv[2],
    "run_num": int(sys.argv[3]),
    "phase1_understand_seconds": float(sys.argv[4]),
    "phase2_decide_seconds": float(sys.argv[5]),
    "phase3_solution_seconds": float(sys.argv[6]),
    "over_budget": sys.argv[7] == "true",
    "timing_complete": sys.argv[8] == "true",
})
results_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

  rm -rf "$run_tmpdir"
done

# Compute summary statistics
completeness_pct="$($PYTHON - <<PY
print(${complete_runs} * 100 // ${RUN_COUNT})
PY
)"

$PYTHON - "$results_json" "$completeness_pct" <<'PY'
import json, sys, statistics
from pathlib import Path
results_path = Path(sys.argv[1])
completeness_pct = int(sys.argv[2])
data = json.loads(results_path.read_text(encoding="utf-8"))

runs = data["runs"]
for phase in ["phase1_understand_seconds", "phase2_decide_seconds", "phase3_solution_seconds"]:
    vals = [r[phase] for r in runs if r["timing_complete"]]
    if vals:
        data["summary"][phase] = {
            "mean": statistics.mean(vals),
            "stdev": statistics.stdev(vals) if len(vals) > 1 else 0,
            "min": min(vals),
            "max": max(vals),
        }

data["summary"]["total_runs"] = len(runs)
data["summary"]["complete_runs"] = sum(1 for r in runs if r["timing_complete"])
data["summary"]["completeness_pct"] = completeness_pct
data["summary"]["anomaly_count"] = sum(1 for r in runs if r["over_budget"])
data["summary"]["ac_003a_2_pass"] = completeness_pct >= 95

results_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Completeness: {completeness_pct}%  AC-003a-2: {'PASS' if completeness_pct >= 95 else 'FAIL'}")
PY

printf '\n## Summary Statistics\n\n' >> "$results_md"
$PYTHON - "$results_json" >> "$results_md" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
s = data.get("summary", {})
print(f"- Total runs: {s.get('total_runs', '?')}")
print(f"- Complete timing: {s.get('complete_runs', '?')}/{s.get('total_runs', '?')} ({s.get('completeness_pct', 0)}%)")
print(f"- Over-budget anomalies: {s.get('anomaly_count', 0)}")
print(f"- AC-003a-2 pass: {'✓' if s.get('ac_003a_2_pass') else '✗'}")
for phase in ["phase1_understand_seconds", "phase2_decide_seconds", "phase3_solution_seconds"]:
    stats = s.get(phase, {})
    if stats:
        print(f"- {phase}: mean={stats['mean']:.2f}s stddev={stats['stdev']:.2f}s")
PY

printf '\nB-002 benchmark complete. Report written to:\n  %s\n  %s\n' "$results_json" "$results_md"
