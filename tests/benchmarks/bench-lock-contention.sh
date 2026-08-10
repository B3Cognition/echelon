#!/usr/bin/env bash
# T034: Benchmark B-001 — Lock Contention
# Measures wait durations under different concurrency levels and hold times.
# Reports P50/P95/P99 wait durations, timeout count, and pending queue volume.
# Output: JSON + markdown in tests/benchmarks/reports/
set -uo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/runtime/scripts/bash"
FIXTURES="$REPO_ROOT/tests/fixtures/kb/valid-seeds"
REPORTS_DIR="$REPO_ROOT/tests/benchmarks/reports"
KB_DIR="$REPO_ROOT/knowledge-base"
LOCK_DIR="$KB_DIR/.locks/kb-write.lock"

mkdir -p "$REPORTS_DIR"

cleanup() {
  rm -rf "$LOCK_DIR"
  [[ -d "${KB_DIR}/.pending" ]] && rm -rf "${KB_DIR}/.pending"
}
trap cleanup EXIT

# Scenarios: (writer_count, hold_seconds)
SCENARIOS=(
  "2 29"
  "2 30"
  "2 31"
  "5 10"
)

tmpdir="$(mktemp -d)"
results_json="$REPORTS_DIR/lock-contention.json"
results_md="$REPORTS_DIR/lock-contention.md"

printf '{"scenarios":[]}\n' > "$results_json"

printf '# B-001: Lock Contention Benchmark\n\n' > "$results_md"
printf 'Generated: %s\n\n' "$($PYTHON -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')" >> "$results_md"
printf '| Writers | Hold (s) | P50 wait (ms) | P95 wait (ms) | P99 wait (ms) | Timeouts | Pending queue |\n' >> "$results_md"
printf '|---------|----------|---------------|---------------|---------------|----------|---------------|\n' >> "$results_md"

for scenario in "${SCENARIOS[@]}"; do
  writer_count="${scenario%% *}"
  hold_seconds="${scenario##* }"

  printf '[B-001] writers=%s hold=%ss ...\n' "$writer_count" "$hold_seconds"
  cleanup
  rm -rf "$LOCK_DIR"

  test_kb="$tmpdir/estimates-log-${writer_count}-${hold_seconds}.yaml"
  cp "$FIXTURES/estimates-log.yaml" "$test_kb"

  wait_times=()
  timeouts=0
  pending_count=0

  # Launch holder in the background that holds lock for hold_seconds
  (
    bash "$SCRIPTS/kb-lock.sh" acquire --run-id "bench-holder" >/dev/null 2>&1
    sleep "$hold_seconds"
    bash "$SCRIPTS/kb-lock.sh" release --run-id "bench-holder" >/dev/null 2>&1
  ) &
  HOLDER_PID=$!

  # Give holder a moment to acquire the lock
  sleep 0.5

  # Launch writer_count-1 contenders (holder counts as one)
  contender_pids=()
  for i in $(seq 2 "$writer_count"); do
    wait_file="$tmpdir/wait-${writer_count}-${hold_seconds}-${i}.txt"
    (
      start_ms="$($PYTHON -c 'import time; print(int(time.time()*1000))')"
      set +e
      bash "$SCRIPTS/kb-lock.sh" acquire --run-id "bench-contender-${i}" >/dev/null 2>&1
      lock_rc=$?
      set -e
      end_ms="$($PYTHON -c 'import time; print(int(time.time()*1000))')"
      elapsed=$((end_ms - start_ms))

      if [[ "$lock_rc" -eq 2 ]]; then
        # Timeout: create pending entry
        bash "$SCRIPTS/kb-pending-write.sh" \
          --target-file "$test_kb" \
          --operation append_entry \
          --payload "$(printf 'id: bench-entry-%d\nagent: AUDITOR\ndomain: bench\nestimate_hours: 1\nconfidence: 0.5' "$i")" \
          --run-id "bench-contender-${i}" \
          --agent "AUDITOR" \
          --operation-id "op-bench-${writer_count}-${hold_seconds}-${i}" >/dev/null 2>&1 || true
        printf 'TIMEOUT %s\n' "$elapsed" > "$wait_file"
      else
        printf 'WAIT_MS %s\n' "$elapsed" > "$wait_file"
        bash "$SCRIPTS/kb-lock.sh" release --run-id "bench-contender-${i}" >/dev/null 2>&1 || true
      fi
    ) &
    contender_pids+=("$!")
  done

  wait "$HOLDER_PID" || true
  for pid in "${contender_pids[@]}"; do
    wait "$pid" || true
  done

  # Collect results from wait files
  for i in $(seq 2 "$writer_count"); do
    wait_file="$tmpdir/wait-${writer_count}-${hold_seconds}-${i}.txt"
    if [[ -f "$wait_file" ]]; then
      line="$(cat "$wait_file")"
      if [[ "$line" == TIMEOUT* ]]; then
        timeouts=$((timeouts + 1))
        ms="${line#TIMEOUT }"
        wait_times+=("$ms")
      elif [[ "$line" == WAIT_MS* ]]; then
        ms="${line#WAIT_MS }"
        wait_times+=("$ms")
      fi
    fi
  done

  pending_count="$(find "${KB_DIR}/.pending" -maxdepth 1 -name '*.pending.yaml' 2>/dev/null | wc -l | tr -d ' ')"

  # Compute percentiles
  p50=0; p95=0; p99=0
  if [[ "${#wait_times[@]}" -gt 0 ]]; then
    p50_p95_p99="$($PYTHON - "${wait_times[@]}" <<'PY'
import sys
vals = sorted(int(x) for x in sys.argv[1:])
def pct(arr, p):
    if not arr: return 0
    k = (len(arr)-1)*p/100
    lo, hi = int(k), min(int(k)+1, len(arr)-1)
    return arr[lo]+(arr[hi]-arr[lo])*(k-lo)
print(int(pct(vals,50)), int(pct(vals,95)), int(pct(vals,99)))
PY
)"
    p50="${p50_p95_p99%% *}"
    rest="${p50_p95_p99#* }"
    p95="${rest%% *}"
    p99="${rest##* }"
  fi

  printf '| %s | %s | %s | %s | %s | %s | %s |\n' \
    "$writer_count" "$hold_seconds" "$p50" "$p95" "$p99" "$timeouts" "$pending_count" >> "$results_md"

  # Append scenario to JSON
  $PYTHON - "$results_json" "$writer_count" "$hold_seconds" "$p50" "$p95" "$p99" "$timeouts" "$pending_count" <<'PY'
import json, sys
from pathlib import Path

results_path = Path(sys.argv[1])
data = json.loads(results_path.read_text(encoding="utf-8"))
data["scenarios"].append({
    "writers": int(sys.argv[2]),
    "hold_seconds": int(sys.argv[3]),
    "p50_ms": int(sys.argv[4]),
    "p95_ms": int(sys.argv[5]),
    "p99_ms": int(sys.argv[6]),
    "timeouts": int(sys.argv[7]),
    "pending_queue": int(sys.argv[8]),
})
results_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

  cleanup
  rm -rf "$LOCK_DIR"
done

printf '\n## Acceptance Checks\n\n' >> "$results_md"
# Check: 2 writers, hold=29s → second writer succeeds (0 timeouts)
no_timeout="$($PYTHON - "$results_json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for s in d["scenarios"]:
    if s["writers"]==2 and s["hold_seconds"]==29:
        print("PASS" if s["timeouts"]==0 else f"FAIL: {s['timeouts']} timeouts")
        break
else:
    print("SKIP: scenario not found")
PY
)"
printf -- '- 2 writers hold=29s, second succeeds: **%s**\n' "$no_timeout" >> "$results_md"

# Check: 2 writers, hold=31s → second writer times out
timeout_check="$($PYTHON - "$results_json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for s in d["scenarios"]:
    if s["writers"]==2 and s["hold_seconds"]==31:
        print("PASS" if s["timeouts"]>=1 else f"FAIL: {s['timeouts']} timeouts")
        break
else:
    print("SKIP: scenario not found")
PY
)"
printf -- '- 2 writers hold=31s, second times out: **%s**\n' "$timeout_check" >> "$results_md"

rm -rf "$tmpdir"

printf '\nB-001 benchmark complete. Report written to:\n  %s\n  %s\n' "$results_json" "$results_md"
