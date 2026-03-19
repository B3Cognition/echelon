#!/usr/bin/env bash
# T031: Integration — Phase Timing Summary Linkage
# Simulates 3 phases start+end, then writes timing_summary entries to journal.
# Covers TEST-003a-3: journal values match state.json phase_timings.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts/bash"

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

# write_timing_summary: reads all phase_timings from state.json and appends
# one timing_summary journal entry per phase (COMMANDER run-close logic).
write_timing_summary() {
  local state_file="$1"
  local journal_file="$2"
  local run_id="$3"

  python3 - "$state_file" "$journal_file" "$run_id" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path = Path(sys.argv[1])
journal_path = Path(sys.argv[2])
run_id = sys.argv[3]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

state = json.loads(state_path.read_text(encoding="utf-8"))
journal_data = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"entries": []}
entries = journal_data.setdefault("entries", [])

phase_timings = state.get("phase_timings", {})
for phase_key, timing in phase_timings.items():
    entries.append({
        "type": "timing_summary",
        "phase": phase_key,
        "run_id": run_id,
        "elapsed_seconds": timing.get("elapsed_seconds"),
        "budget_seconds": timing.get("budget_seconds"),
        "over_budget": timing.get("over_budget"),
        "anomaly_reason": timing.get("anomaly_reason"),
        "timestamp": now,
    })

tmp = journal_path.with_name(journal_path.name + f".tmp.{os.getpid()}")
tmp.write_text(json.dumps(journal_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp, journal_path)
PY
}

# Setup: temporary state + journal files
tmpdir="$(mktemp -d)"
state_file="$tmpdir/state.json"
journal_file="$tmpdir/journal.json"
printf '{"run_id":"int-timing-001"}\n' > "$state_file"
printf '{"entries":[]}\n' > "$journal_file"

RUN_ID="int-timing-001"
PHASES=("phase1-understand" "phase2-decide" "phase3-solution")
BUDGETS=(2400 1800 2400)

# Simulate 3 phases: start → 1s work → end
for i in 0 1 2; do
  pkey="${PHASES[$i]}"
  budget="${BUDGETS[$i]}"
  bash "$SCRIPTS/phase-timing.sh" start_phase "$pkey" "$budget" --state-file "$state_file"
  sleep 1
  bash "$SCRIPTS/phase-timing.sh" end_phase "$pkey" \
    --state-file "$state_file" \
    --journal-file "$journal_file" \
    --run-id "$RUN_ID"
done

# Write run-close timing_summary
write_timing_summary "$state_file" "$journal_file" "$RUN_ID"

# Assertions: timing_summary entries exist for all 3 phases
for pkey in "${PHASES[@]}"; do
  assert "INT-003a-3: timing_summary for $pkey in journal" "$(
    python3 - "$journal_file" "$pkey" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
entries = [e for e in d.get("entries", []) if e.get("type")=="timing_summary" and e.get("phase")==sys.argv[2]]
print("OK" if entries else "FAIL:not found")
PY
  )"
done

# Assertions: journal values match state.json (no drift)
for pkey in "${PHASES[@]}"; do
  state_elapsed="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('phase_timings',{}).get('$pkey',{}).get('elapsed_seconds',-1))")"
  journal_elapsed="$(python3 - "$journal_file" "$pkey" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
entries = [e for e in d.get("entries",[]) if e.get("type")=="timing_summary" and e.get("phase")==sys.argv[2]]
print(entries[0].get("elapsed_seconds",-1) if entries else -1)
PY
)"
  assert "INT-003a-3: elapsed_seconds matches between state and journal for $pkey" "$(
    python3 - "$state_elapsed" "$journal_elapsed" <<'PY'
import sys
se = float(sys.argv[1])
je = float(sys.argv[2])
# Allow up to 1s drift due to test timing
diff = abs(se - je)
print("OK" if diff <= 1.0 else f"FAIL:state_elapsed={se:.2f} journal_elapsed={je:.2f}")
PY
  )"
done

# Assert exactly one timing_summary per phase (no duplicates)
for pkey in "${PHASES[@]}"; do
  count="$(python3 - "$journal_file" "$pkey" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
entries = [e for e in d.get("entries",[]) if e.get("type")=="timing_summary" and e.get("phase")==sys.argv[2]]
print(len(entries))
PY
)"
  assert "INT-003a-3: exactly 1 timing_summary per phase ($pkey)" "$(
    [[ "$count" == "1" ]] && ok_result || fail_result "count=$count"
  )"
done

rm -rf "$tmpdir"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
