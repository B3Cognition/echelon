#!/usr/bin/env bash
# T022: Unit tests — Story 001c Recovery State Reset
# Simulates the COMMANDER preflight recovery logic: starting from fallback_mode=true,
# then running preflight with mock-available, and asserting fallback_mode cleared and
# fallback_recovery journal entry written.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts/bash"
MOCKS="$REPO_ROOT/tests/mocks"
FIXTURES="$REPO_ROOT/tests/fixtures"

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

# Applies the COMMANDER preflight-recovery logic inline.
# Given the preflight exit code and current state, updates state + journal.
apply_commander_preflight_recovery() {
  local state_file="$1"
  local journal_file="$2"
  local preflight_rc="$3"
  local run_id="$4"
  local prior_run_id="$5"

  python3 - "$state_file" "$journal_file" "$preflight_rc" "$run_id" "$prior_run_id" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path = Path(sys.argv[1])
journal_path = Path(sys.argv[2])
preflight_rc = int(sys.argv[3])
run_id = sys.argv[4]
prior_run_id = sys.argv[5]

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

state = json.loads(state_path.read_text(encoding="utf-8"))
journal_data = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"entries": []}
entries = journal_data.setdefault("entries", [])

if preflight_rc == 0:
    # Recovery path: spec-kit available after prior fallback
    if state.get("fallback_mode"):
        state["fallback_mode"] = False
        fallbacks = [f for f in state.get("dependency_fallbacks", []) if f != "spec-kit"]
        state["dependency_fallbacks"] = fallbacks
        entries.append({
            "type": "fallback_recovery",
            "dependency": "spec-kit",
            "prior_run_id": prior_run_id,
            "recovery_run_id": run_id,
            "timestamp": now,
        })
else:
    # Fallback path
    state["fallback_mode"] = True
    state["execution_mode"] = "manual_specification"
    fallbacks = state.get("dependency_fallbacks", [])
    if "spec-kit" not in fallbacks:
        fallbacks.append("spec-kit")
    state["dependency_fallbacks"] = fallbacks
    entries.append({
        "type": "dependency_failure",
        "dependency": "spec-kit",
        "phase": "phase1-understand",
        "fallback_mode": True,
        "timestamp": now,
    })

tmp_s = state_path.with_name(state_path.name + f".tmp.{os.getpid()}")
tmp_s.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp_s, state_path)

tmp_j = journal_path.with_name(journal_path.name + f".tmp.{os.getpid()}")
tmp_j.write_text(json.dumps(journal_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp_j, journal_path)
PY
}

ORIG_CONF=""
ORIG_CONF=""
[[ -f "$MOCKS/spec-kit.conf" ]] && ORIG_CONF="$(cat "$MOCKS/spec-kit.conf")"
TMPWRAP="$(mktemp -d)"
restore_all() {
  [[ -n "${ORIG_CONF:-}" ]] && printf '%s\n' "$ORIG_CONF" > "$MOCKS/spec-kit.conf"
  rm -rf "${TMPWRAP:-}"
}
trap restore_all EXIT

# Helper: create executable wrapper for mock
create_wrapper() {
  local mode="$1"
  local timeout_seconds="${2:-3}"
  printf 'mode=%s\ntimeout_seconds=%s\n' "$mode" "$timeout_seconds" > "$MOCKS/spec-kit.conf"
  printf '#!/usr/bin/env bash\nexec bash "%s" "$@"\n' "$MOCKS/spec-kit" > "$TMPWRAP/spec-kit"
  chmod +x "$TMPWRAP/spec-kit"
}

# TEST-001c-1: fallback_mode=true + available preflight → fallback_mode=false --------------

tmpdir="$(mktemp -d)"
state_file="$tmpdir/state.json"
journal_file="$tmpdir/journal.json"

# Start from fallback-mode state
cp "$FIXTURES/state/fallback-mode.json" "$state_file"
cp "$FIXTURES/journal/baseline.json" "$journal_file"

prior_run_id="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('run_id','unknown'))")"
recovery_run_id="squad-recovery-$(date +%s)"

# Run preflight with available mock
create_wrapper available
set +e
PATH="$TMPWRAP:$PATH" bash "$SCRIPTS/preflight-speckit.sh" --cmd spec-kit >/dev/null 2>&1
preflight_rc=$?
set -e

apply_commander_preflight_recovery "$state_file" "$journal_file" "$preflight_rc" "$recovery_run_id" "$prior_run_id"

# Assert fallback_mode=false
fallback_mode="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('fallback_mode', 'absent'))")"
assert "TEST-001c-1: fallback_mode is false after available preflight" "$(
  [[ "$fallback_mode" != "True" && "$fallback_mode" != "true" ]] && ok_result || fail_result "fallback_mode=$fallback_mode"
)"

# Assert spec-kit removed from dependency_fallbacks
dep_fallbacks="$(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('dependency_fallbacks', []))")"
assert "TEST-001c-1: spec-kit removed from dependency_fallbacks" "$(
  # dependency_fallbacks should be empty or not contain spec-kit
  python3 -c "import json; d=json.load(open('$state_file')); fallbacks=d.get('dependency_fallbacks',[]); exit(0 if 'spec-kit' not in fallbacks else 1)" \
    && ok_result || fail_result "dependency_fallbacks=$dep_fallbacks"
)"

# Assert fallback_recovery journal entry with prior_run_id and recovery_run_id
recovery_entry="$(python3 -c "
import json
d=json.load(open('$journal_file'))
entries=[e for e in d.get('entries',[]) if e.get('type')=='fallback_recovery']
if entries:
    e=entries[-1]
    if e.get('prior_run_id') and e.get('recovery_run_id'):
        print('found')
    else:
        print('missing_run_ids')
else:
    print('missing_entry')
")"
assert "TEST-001c-1: fallback_recovery journal entry with both run IDs" "$(
  [[ "$recovery_entry" == "found" ]] && ok_result || fail_result "journal check=$recovery_entry"
)"

rm -rf "$tmpdir"

# TEST-001c-2 (negative): starting from non-fallback state → unavailable preflight writes fallback fields

tmpdir2="$(mktemp -d)"
state_file2="$tmpdir2/state.json"
journal_file2="$tmpdir2/journal.json"

cp "$FIXTURES/state/baseline.json" "$state_file2"
cp "$FIXTURES/journal/baseline.json" "$journal_file2"

prior_id2="$(python3 -c "import json; d=json.load(open('$state_file2')); print(d.get('run_id','unknown'))")"
new_run_id2="squad-test2-$(date +%s)"

set +e
bash "$SCRIPTS/preflight-speckit.sh" --cmd /nonexistent/speckit-x >/dev/null 2>&1
prc2=$?
set -e

apply_commander_preflight_recovery "$state_file2" "$journal_file2" "$prc2" "$new_run_id2" "$prior_id2"

# Assert fallback_mode=true
fbm="$(python3 -c "import json; d=json.load(open('$state_file2')); print(d.get('fallback_mode', 'absent'))")"
assert "TEST-001c-2: unavailable preflight sets fallback_mode=true" "$(
  [[ "$fbm" == "True" ]] && ok_result || fail_result "fallback_mode=$fbm"
)"

# Assert dependency_failure journal entry
dep_entry="$(python3 -c "
import json
d=json.load(open('$journal_file2'))
entries=[e for e in d.get('entries',[]) if e.get('type')=='dependency_failure']
print('found' if entries else 'missing')
")"
assert "TEST-001c-2: dependency_failure journal entry written on unavailable" "$(
  [[ "$dep_entry" == "found" ]] && ok_result || fail_result "journal check=$dep_entry"
)"

rm -rf "$tmpdir2"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
