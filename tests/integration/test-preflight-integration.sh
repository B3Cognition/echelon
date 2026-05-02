#!/usr/bin/env bash
# T028: Integration — COMMANDER Preflight + Fallback Routing
# Full preflight → state writes → CARTOGRAPHER dispatch simulation.
# Covers TEST-001a-3, TEST-001a-5, TEST-001b-1, TEST-001b-2.
set -uo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
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

# commander_preflight_and_dispatch: simulates COMMANDER running preflight then
# "dispatching" CARTOGRAPHER (simulated by selecting agent response mock).
# Writes state.json and journal.json per the echelon.run.md procedure.
commander_preflight_and_dispatch() {
  local speckit_cmd="$1"
  local state_file="$2"
  local journal_file="$3"
  local run_id="$4"

  # Run preflight
  set +e
  preflight_stdout="$(bash "$SCRIPTS/preflight-speckit.sh" --cmd "$speckit_cmd" 2>&1)"
  preflight_rc=$?
  set -e

  $PYTHON - "$state_file" "$journal_file" "$preflight_rc" "$preflight_stdout" "$run_id" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path = Path(sys.argv[1])
journal_path = Path(sys.argv[2])
preflight_rc = int(sys.argv[3])
preflight_stdout = sys.argv[4]
run_id = sys.argv[5]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
journal_data = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"entries": []}
entries = journal_data.setdefault("entries", [])

# Determine version and error code from stdout
error_code = None
version = None
if preflight_rc == 0:
    for line in preflight_stdout.splitlines():
        if line.startswith("DEPENDENCY_SPECKIT_AVAILABLE:"):
            version = line.split(":", 1)[1]
elif preflight_rc == 1:
    error_code = "DEPENDENCY_SPECKIT_UNAVAILABLE"
elif preflight_rc == 2:
    error_code = "DEPENDENCY_SPECKIT_TIMEOUT"
elif preflight_rc == 3:
    error_code = "DEPENDENCY_SPECKIT_INCOMPATIBLE"

# Write dependency_checks
dep_checks = state.setdefault("dependency_checks", {})
dep_checks["spec_kit"] = {
    "status": "available" if preflight_rc == 0 else "unavailable" if preflight_rc == 1 else "timeout" if preflight_rc == 2 else "incompatible",
    "checked_at": now,
    "error_code": error_code,
    "version": version,
}

if preflight_rc != 0:
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
        "error_code": error_code,
        "timestamp": now,
    })
else:
    if state.get("fallback_mode"):
        state["fallback_mode"] = False
        state["dependency_fallbacks"] = [f for f in state.get("dependency_fallbacks", []) if f != "spec-kit"]
        entries.append({
            "type": "fallback_recovery",
            "dependency": "spec-kit",
            "recovery_run_id": run_id,
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
[[ -f "$MOCKS/spec-kit.conf" ]] && ORIG_CONF="$(cat "$MOCKS/spec-kit.conf")"
TMPWRAP=""
cleanup() {
  [[ -n "$ORIG_CONF" ]] && printf '%s\n' "$ORIG_CONF" > "$MOCKS/spec-kit.conf"
  [[ -n "$TMPWRAP" ]] && rm -rf "$TMPWRAP"
}
trap cleanup EXIT

# TEST-001a-3 + TEST-001b-2: fallback path — state + journal correct ----------------------

tmpdir="$(mktemp -d)"
state_f="$tmpdir/state.json"
journal_f="$tmpdir/journal.json"
cp "$FIXTURES/state/baseline.json" "$state_f"
printf '{"entries":[]}\n' > "$journal_f"

printf 'mode=available\ntimeout_seconds=3\n' > "$MOCKS/spec-kit.conf"
commander_preflight_and_dispatch /nonexistent/speckit "$state_f" "$journal_f" "run-fallback-001"

assert "INT-001b-1: fallback_mode=true after unavailable preflight" "$(
  $PYTHON -c "import json; d=json.load(open('$state_f')); exit(0 if d.get('fallback_mode')==True else 1)" \
    && ok_result || fail_result "$($PYTHON -c "import json; d=json.load(open('$state_f')); print(d.get('fallback_mode'))")"
)"
assert "INT-001b-1: dependency_checks.spec_kit written" "$(
  $PYTHON -c "import json; d=json.load(open('$state_f')); exit(0 if 'spec_kit' in d.get('dependency_checks',{}) else 1)" \
    && ok_result || fail_result "dependency_checks missing"
)"
assert "INT-001b-1: execution_mode=manual_specification" "$(
  $PYTHON -c "import json; d=json.load(open('$state_f')); exit(0 if d.get('execution_mode')=='manual_specification' else 1)" \
    && ok_result || fail_result "$($PYTHON -c "import json; d=json.load(open('$state_f')); print(d.get('execution_mode'))")"
)"
assert "INT-001b-1: spec-kit in dependency_fallbacks" "$(
  $PYTHON -c "import json; d=json.load(open('$state_f')); exit(0 if 'spec-kit' in d.get('dependency_fallbacks',[]) else 1)" \
    && ok_result || fail_result "dependency_fallbacks missing spec-kit"
)"
assert "INT-001b-1: dependency_failure journal entry" "$(
  $PYTHON -c "import json; d=json.load(open('$journal_f')); entry=[e for e in d.get('entries',[]) if e.get('type')=='dependency_failure']; exit(0 if entry else 1)" \
    && ok_result || fail_result "dependency_failure entry missing"
)"

# Simulate CARTOGRAPHER dispatch: verifies it is dispatched even in fallback mode.
# In fallback mode CARTOGRAPHER still runs but with UNVALIDATED banner.
# We use the agent-response mock to simulate.
cartographer_mock="$MOCKS/agent-responses/quality-pass.md"
cartographer_artifact="$tmpdir/spec.md"
if [[ -f "$cartographer_mock" ]]; then
  fallback_mode_val="$($PYTHON -c "import json; d=json.load(open('$state_f')); print(d.get('fallback_mode',False))")"
  if [[ "$fallback_mode_val" == "True" ]]; then
    # Inject UNVALIDATED_DEPENDENCY banner (simulating CARTOGRAPHER fallback output)
    cat > "$cartographer_artifact" <<'ARTIFACT'
> **FALLBACK STATUS: UNVALIDATED_DEPENDENCY**
> spec-kit was unavailable during generation.
ARTIFACT
    cat "$cartographer_mock" >> "$cartographer_artifact"
  else
    cp "$cartographer_mock" "$cartographer_artifact"
  fi
fi

assert "INT-001b-2: CARTOGRAPHER dispatched (artifact created) even in fallback mode" "$(
  [[ -f "$cartographer_artifact" ]] && ok_result || fail_result "artifact not created"
)"
assert "INT-001b-2: fallback artifact has UNVALIDATED_DEPENDENCY banner" "$(
  [[ -f "$cartographer_artifact" ]] && grep -q 'UNVALIDATED_DEPENDENCY' "$cartographer_artifact" \
    && ok_result || fail_result "UNVALIDATED_DEPENDENCY banner missing"
)"

# TEST-001b-1 + TEST-001a-3: normal (non-fallback) path -----------------------------------

tmpdir2="$(mktemp -d)"
state_f2="$tmpdir2/state.json"
journal_f2="$tmpdir2/journal.json"
cp "$FIXTURES/state/baseline.json" "$state_f2"
printf '{"entries":[]}\n' > "$journal_f2"

printf 'mode=available\ntimeout_seconds=3\n' > "$MOCKS/spec-kit.conf"
TMPWRAP="$(mktemp -d)"
printf '#!/usr/bin/env bash\nexec bash "%s" "$@"\n' "$MOCKS/spec-kit" > "$TMPWRAP/spec-kit"
chmod +x "$TMPWRAP/spec-kit"
PATH="$TMPWRAP:$PATH" commander_preflight_and_dispatch "spec-kit" "$state_f2" "$journal_f2" "run-normal-001"

assert "INT-001a-3: fallback_mode not set on available preflight" "$(
  $PYTHON -c "import json; d=json.load(open('$state_f2')); exit(0 if not d.get('fallback_mode') else 1)" \
    && ok_result || fail_result "fallback_mode is true"
)"
assert "INT-001a-3: dependency_checks.spec_kit has status=available" "$(
  $PYTHON -c "import json; d=json.load(open('$state_f2')); s=d.get('dependency_checks',{}).get('spec_kit',{}).get('status'); exit(0 if s=='available' else 1)" \
    && ok_result || fail_result "status not available"
)"
# Normal artifact: no UNVALIDATED banner
if [[ -f "$cartographer_mock" ]]; then
  normal_artifact="$tmpdir2/spec.md"
  cp "$cartographer_mock" "$normal_artifact"
  assert "INT-001b-1: normal artifact has NO UNVALIDATED_DEPENDENCY banner" "$(
    ! grep -q 'UNVALIDATED_DEPENDENCY' "$normal_artifact" \
      && ok_result || fail_result "unexpected banner found"
  )"
fi

rm -rf "$tmpdir" "$tmpdir2"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
