#!/usr/bin/env bash
# T027: Unit tests — Story 003a Timing Fields
# Tests phase-timing.sh start_phase and end_phase subcommands.
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

# TEST: start_phase writes start_ts and budget_seconds to state.json ----------------------

tmpdir="$(mktemp -d)"
state_file="$tmpdir/state.json"
printf '{"run_id":"unit-test"}\n' > "$state_file"

bash "$SCRIPTS/phase-timing.sh" start_phase "test-phase-1" 300 --state-file "$state_file"

start_ts="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('phase_timings',{}).get('test-phase-1',{}).get('start_ts','missing'))")"
budget="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('phase_timings',{}).get('test-phase-1',{}).get('budget_seconds','missing'))")"

assert "start_phase: start_ts present in state.json" "$(
  [[ "$start_ts" != "missing" && -n "$start_ts" ]] && ok_result || fail_result "start_ts=$start_ts"
)"
assert "start_phase: budget_seconds=300 in state.json" "$(
  python3 -c "import json; d=json.load(open('$state_file')); b=d.get('phase_timings',{}).get('test-phase-1',{}).get('budget_seconds'); exit(0 if b==300.0 else 1)" \
    && ok_result || fail_result "budget=$budget"
)"
assert "start_phase: start_ts is ISO-8601 format" "$(
  [[ "$start_ts" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
    && ok_result || fail_result "start_ts=$start_ts"
)"
# Verify start_ts is within ±5s of current time
ts_ok="$(python3 - "$start_ts" <<'PY'
import sys
from datetime import datetime, timezone

raw = sys.argv[1]
raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
dt = datetime.fromisoformat(raw)
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)
now = datetime.now(timezone.utc)
diff = abs((now - dt).total_seconds())
print("OK" if diff <= 5 else f"FAIL:ts_diff={diff:.1f}s")
PY
)"
assert "start_phase: start_ts matches current time ±5s" "$ts_ok"

# TEST: end_phase after 1s sleep → elapsed >= 1, over_budget=false (budget=300) -----------

journal_file="$tmpdir/journal1.json"
printf '{"entries":[]}\n' > "$journal_file"

sleep 1

bash "$SCRIPTS/phase-timing.sh" end_phase "test-phase-1" \
  --state-file "$state_file" \
  --journal-file "$journal_file" \
  --run-id "unit-test"

elapsed="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('phase_timings',{}).get('test-phase-1',{}).get('elapsed_seconds',-1))")"
over_budget="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('phase_timings',{}).get('test-phase-1',{}).get('over_budget','not_set'))")"
end_ts="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('phase_timings',{}).get('test-phase-1',{}).get('end_ts','missing'))")"

assert "end_phase: elapsed_seconds >= 1" "$(
  python3 -c "exit(0 if float('$elapsed') >= 1.0 else 1)" \
    && ok_result || fail_result "elapsed=$elapsed"
)"
assert "end_phase: end_ts set" "$(
  [[ "$end_ts" != "missing" && -n "$end_ts" ]] && ok_result || fail_result "end_ts=$end_ts"
)"
assert "end_phase: over_budget=False when within budget" "$(
  [[ "$over_budget" == "False" ]] && ok_result || fail_result "over_budget=$over_budget"
)"
# No timing_anomaly in journal for on-budget phase
anomaly_count="$(python3 -c "import json; d=json.load(open('$journal_file')); entries=[e for e in d.get('entries',[]) if e.get('type')=='timing_anomaly']; print(len(entries))")"
assert "end_phase: no timing_anomaly in journal for on-budget phase" "$(
  [[ "$anomaly_count" == "0" ]] && ok_result || fail_result "anomaly_count=$anomaly_count"
)"

# TEST: end_phase after 2s for 1s budget → over_budget=true, anomaly_reason set ----------

state_file2="$tmpdir/state2.json"
journal_file2="$tmpdir/journal2.json"
printf '{"run_id":"unit-test-2"}\n' > "$state_file2"
printf '{"entries":[]}\n' > "$journal_file2"

bash "$SCRIPTS/phase-timing.sh" start_phase "tight-phase" 1 --state-file "$state_file2"
sleep 2

bash "$SCRIPTS/phase-timing.sh" end_phase "tight-phase" \
  --state-file "$state_file2" \
  --journal-file "$journal_file2" \
  --run-id "unit-test-2"

over_budget2="$(python3 -c "import json; d=json.load(open('$state_file2')); print(d.get('phase_timings',{}).get('tight-phase',{}).get('over_budget','not_set'))")"
anomaly_reason="$(python3 -c "import json; d=json.load(open('$state_file2')); print(d.get('phase_timings',{}).get('tight-phase',{}).get('anomaly_reason','not_set'))")"

assert "end_phase: over_budget=True when elapsed > budget * 1.2" "$(
  [[ "$over_budget2" == "True" ]] && ok_result || fail_result "over_budget=$over_budget2"
)"
assert "end_phase: anomaly_reason=EXCEEDED_BUDGET_20_PERCENT" "$(
  [[ "$anomaly_reason" == "EXCEEDED_BUDGET_20_PERCENT" ]] \
    && ok_result || fail_result "anomaly_reason=$anomaly_reason"
)"

# timing_anomaly journal entry written for over-budget phase
anomaly_entry="$(python3 -c "
import json
d=json.load(open('$journal_file2'))
entries=[e for e in d.get('entries',[]) if e.get('type')=='timing_anomaly']
if entries:
    e=entries[0]
    if e.get('anomaly_reason')=='EXCEEDED_BUDGET_20_PERCENT' and e.get('phase')=='tight-phase':
        print('OK')
    else:
        print('FAIL:wrong_content:' + str(e))
else:
    print('FAIL:no_entry')
")"
assert "end_phase: timing_anomaly journal entry with correct fields" "$(
  [[ "$anomaly_entry" == "OK" ]] && ok_result || fail_result "$anomaly_entry"
)"

rm -rf "$tmpdir"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
