#!/usr/bin/env bash
# T032: E2E — Fallback Run Baseline
# Full squad phase1-understand simulation through fallback → recovery cycle.
# Covers TEST-001b-3, TEST-001b-4, TEST-001c-1.
# Runs in an isolated tmpdir; does NOT modify real knowledge-base or .specify/squad/.
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

# Simulates a squad run through phase1-understand including preflight + CARTOGRAPHER dispatch.
# state_file, journal_file, and artifact_dir are in tmpdir.
simulate_squad_run() {
  local speckit_cmd="$1"
  local run_id="$2"
  local state_file="$3"
  local journal_file="$4"
  local artifact_dir="$5"
  local prior_state_file="${6:-}"

  mkdir -p "$artifact_dir"

  # Initialize state from prior state if exists (recovery scenario)
  if [[ -n "$prior_state_file" && -f "$prior_state_file" ]]; then
    cp "$prior_state_file" "$state_file"
  elif [[ ! -f "$state_file" ]]; then
    printf '{"run_id":"%s","status":"running","phase":"init"}\n' "$run_id" > "$state_file"
  fi
  [[ -f "$journal_file" ]] || printf '{"entries":[]}\n' > "$journal_file"

  # Run preflight
  set +e
  preflight_stdout="$(bash "$SCRIPTS/preflight-speckit.sh" --cmd "$speckit_cmd" 2>&1)"
  preflight_rc=$?
  set -e

  python3 - "$state_file" "$journal_file" \
            "$preflight_rc" "$preflight_stdout" \
            "$run_id" "$artifact_dir" <<'PY'
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
artifact_dir = Path(sys.argv[6])
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

state = json.loads(state_path.read_text(encoding="utf-8"))
journal_data = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"entries": []}
entries = journal_data.setdefault("entries", [])

# Determine outcome
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

dep_checks = state.setdefault("dependency_checks", {})
dep_checks["spec_kit"] = {
    "status": "available" if preflight_rc == 0 else "unavailable" if preflight_rc == 1 else "timeout" if preflight_rc == 2 else "incompatible",
    "checked_at": now,
    "error_code": error_code,
    "version": version,
}

prior_fallback = state.get("fallback_mode", False)

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
    if prior_fallback:
        state["fallback_mode"] = False
        state["dependency_fallbacks"] = [f for f in state.get("dependency_fallbacks", []) if f != "spec-kit"]
        entries.append({
            "type": "fallback_recovery",
            "dependency": "spec-kit",
            "recovery_run_id": run_id,
            "timestamp": now,
        })

# Simulate CARTOGRAPHER dispatch: always dispatched (AC-001a-4)
fallback_mode = state.get("fallback_mode", False)
spec_content = ""
if fallback_mode:
    spec_content = (
        "> **FALLBACK STATUS: UNVALIDATED_DEPENDENCY**\n"
        "> spec-kit was unavailable during generation.\n"
        f"> **Run ID**: {run_id} | **Detected**: {now}\n"
        "> **Provenance**: manual_specification mode — spec-kit branch automation not applied.\n"
        "> **Remediation**: See `.specify/squad/error.log` and recovery checklist.\n\n"
        "# spec.md\n\n(generated in fallback mode)\n"
    )
else:
    spec_content = "# spec.md\n\n(generated normally)\n"

(artifact_dir / "spec.md").write_text(spec_content, encoding="utf-8")
state["status"] = "phase1-complete"
state["phase"] = "phase1-understand"

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

# E2E RUN 1: spec-kit missing → fallback mode ----------------------------------------

tmpdir="$(mktemp -d)"
state1="$tmpdir/state-run1.json"
journal1="$tmpdir/journal-run1.json"
artifacts1="$tmpdir/artifacts-run1"

simulate_squad_run /nonexistent/speckit "e2e-run-001" "$state1" "$journal1" "$artifacts1"

assert "E2E-001b-3: run completes without uncaught exception (no error exit)" "$(
  [[ $? -eq 0 ]] && ok_result || fail_result "simulate_squad_run failed"
)"
assert "E2E-001b-3: fallback_mode=true in state.json" "$(
  python3 -c "import json; d=json.load(open('$state1')); exit(0 if d.get('fallback_mode')==True else 1)" \
    && ok_result || fail_result "$(python3 -c "import json; d=json.load(open('$state1')); print(d)")"
)"
assert "E2E-001b-3: execution_mode=manual_specification" "$(
  python3 -c "import json; d=json.load(open('$state1')); exit(0 if d.get('execution_mode')=='manual_specification' else 1)" \
    && ok_result || fail_result "mode=$(python3 -c "import json; d=json.load(open('$state1')); print(d.get('execution_mode'))")"
)"
assert "E2E-001b-4: spec.md artifact created (CARTOGRAPHER not blocked)" "$(
  [[ -f "$artifacts1/spec.md" ]] && ok_result || fail_result "spec.md not found"
)"
assert "E2E-001b-3: spec.md has UNVALIDATED_DEPENDENCY banner" "$(
  grep -q 'UNVALIDATED_DEPENDENCY' "$artifacts1/spec.md" && ok_result || fail_result "banner missing"
)"
assert "E2E-001b-3: dependency_failure entry in journal" "$(
  python3 -c "import json; d=json.load(open('$journal1')); e=[x for x in d.get('entries',[]) if x.get('type')=='dependency_failure']; exit(0 if e else 1)" \
    && ok_result || fail_result "dependency_failure missing"
)"

# E2E RUN 2: spec-kit available → fallback_recovery clears state ----------------------

printf 'mode=available\ntimeout_seconds=3\n' > "$MOCKS/spec-kit.conf"
TMPWRAP="$(mktemp -d)"
printf '#!/usr/bin/env bash\nexec bash "%s" "$@"\n' "$MOCKS/spec-kit" > "$TMPWRAP/spec-kit"
chmod +x "$TMPWRAP/spec-kit"
state2="$tmpdir/state-run2.json"
journal2="$tmpdir/journal-run2.json"
artifacts2="$tmpdir/artifacts-run2"

PATH="$TMPWRAP:$PATH" simulate_squad_run "spec-kit" "e2e-run-002" "$state2" "$journal2" "$artifacts2" "$state1"

assert "E2E-001c-1: fallback_mode=false after available preflight on run2" "$(
  python3 -c "import json; d=json.load(open('$state2')); exit(0 if not d.get('fallback_mode') else 1)" \
    && ok_result || fail_result "fallback_mode still true"
)"
assert "E2E-001c-1: fallback_recovery journal entry on run2" "$(
  python3 -c "import json; d=json.load(open('$journal2')); e=[x for x in d.get('entries',[]) if x.get('type')=='fallback_recovery']; exit(0 if e else 1)" \
    && ok_result || fail_result "fallback_recovery missing"
)"
assert "E2E-001b-1: run2 spec.md has NO UNVALIDATED_DEPENDENCY banner" "$(
  ! grep -q 'UNVALIDATED_DEPENDENCY' "$artifacts2/spec.md" \
    && ok_result || fail_result "unexpected banner found"
)"
assert "E2E-001c-1: spec-kit removed from dependency_fallbacks on run2" "$(
  python3 -c "import json; d=json.load(open('$state2')); exit(0 if 'spec-kit' not in d.get('dependency_fallbacks',[]) else 1)" \
    && ok_result || fail_result "spec-kit still in dependency_fallbacks"
)"

rm -rf "$tmpdir"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
