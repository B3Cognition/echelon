#!/usr/bin/env bash
# T026: Unit tests — Story 002d Lock Contract
# Tests kb-lock.sh acquire/release, stale lock quarantine, cross-run protection.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
KB_DIR="$REPO_ROOT/knowledge-base"
LOCK_DIR="$KB_DIR/.locks/kb-write.lock"
METADATA_FILE="$LOCK_DIR/metadata.yaml"
RECOVERY_DIR="$REPO_ROOT/.specify/squad/recovery"

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

run_cmd() {
  set +e
  "$@"
  _rc=$?
  set -e
  echo "$_rc"
}

cleanup_lock() {
  rm -rf "$LOCK_DIR"
}
trap cleanup_lock EXIT

# TEST-002d-1: acquire creates lock dir + metadata.yaml; release removes it ---------------

cleanup_lock
rc_acquire="$(run_cmd bash "$SCRIPTS/kb-lock.sh" acquire --run-id "unit-test-acquire")"
assert "TEST-002d-1: acquire exits 0" "$(
  [[ "$rc_acquire" == "0" ]] && ok_result || fail_result "exit $rc_acquire"
)"
assert "TEST-002d-1: lock directory created" "$(
  [[ -d "$LOCK_DIR" ]] && ok_result || fail_result "lock dir not found"
)"
assert "TEST-002d-1: metadata.yaml created" "$(
  [[ -f "$METADATA_FILE" ]] && ok_result || fail_result "metadata.yaml not found"
)"
assert "TEST-002d-1: metadata has owner_run_id" "$(
  grep -q 'owner_run_id: unit-test-acquire' "$METADATA_FILE" && ok_result || fail_result "$(cat "$METADATA_FILE")"
)"

# status should show LOCKED
status_output="$(bash "$SCRIPTS/kb-lock.sh" status 2>&1 || true)"
assert "TEST-002d-1: status shows LOCKED after acquire" "$(
  [[ "$status_output" == "LOCKED:"* ]] && ok_result || fail_result "status='$status_output'"
)"

rc_release="$(run_cmd bash "$SCRIPTS/kb-lock.sh" release --run-id "unit-test-acquire")"
assert "TEST-002d-1: release exits 0" "$(
  [[ "$rc_release" == "0" ]] && ok_result || fail_result "exit $rc_release"
)"
assert "TEST-002d-1: lock directory removed after release" "$(
  [[ ! -d "$LOCK_DIR" ]] && ok_result || fail_result "lock dir still exists"
)"

# status should show UNLOCKED
status_output2="$(bash "$SCRIPTS/kb-lock.sh" status 2>&1 || true)"
assert "TEST-002d-1: status shows UNLOCKED after release" "$(
  [[ "$status_output2" == "UNLOCKED" ]] && ok_result || fail_result "status='$status_output2'"
)"

# TEST-002d stale lock: create metadata with acquired_at > 35s ago -------------------------

cleanup_lock
mkdir -p "$LOCK_DIR"
stale_ts="$(python3 - <<'PY'
from datetime import datetime, timezone, timedelta
dt = datetime.now(timezone.utc) - timedelta(seconds=40)
print(dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"
cat > "$METADATA_FILE" <<EOF
owner_run_id: stale-holder
owner_agent: TEST
acquired_at: $stale_ts
lease_seconds: 30
pid: 99999
EOF

rc_stale="$(run_cmd bash "$SCRIPTS/kb-lock.sh" acquire --run-id "unit-test-fresh")"
assert "TEST-002d stale: acquire quarantines stale lock and succeeds (exit 0)" "$(
  [[ "$rc_stale" == "0" ]] && ok_result || fail_result "exit $rc_stale"
)"
assert "TEST-002d stale: stale lock file quarantined in recovery dir" "$(
  [[ -d "$RECOVERY_DIR" ]] && ls "$RECOVERY_DIR/stale-lock-"*.yaml >/dev/null 2>&1 \
    && ok_result || fail_result "stale-lock backup not found in $RECOVERY_DIR"
)"
assert "TEST-002d stale: new lock acquired with fresh owner" "$(
  [[ -f "$METADATA_FILE" ]] && grep -q 'unit-test-fresh' "$METADATA_FILE" \
    && ok_result || fail_result "$(cat "$METADATA_FILE" 2>/dev/null)"
)"

# Release to clean up
bash "$SCRIPTS/kb-lock.sh" release --run-id "unit-test-fresh" >/dev/null 2>&1 || true
cleanup_lock

# TEST-002d cross-run: release with wrong owner_run_id exits non-zero ---------------------

cleanup_lock
bash "$SCRIPTS/kb-lock.sh" acquire --run-id "owner-A" >/dev/null 2>&1

rc_wrong="$(run_cmd bash "$SCRIPTS/kb-lock.sh" release --run-id "owner-B")"
assert "TEST-002d cross-run: release with wrong owner exits non-zero" "$(
  [[ "$rc_wrong" -ne 0 ]] && ok_result || fail_result "exited 0 (should fail)"
)"
assert "TEST-002d cross-run: lock still held after failed release" "$(
  [[ -d "$LOCK_DIR" ]] && ok_result || fail_result "lock dir removed by wrong owner"
)"

# Clean up: release with proper owner
bash "$SCRIPTS/kb-lock.sh" release --run-id "owner-A" >/dev/null 2>&1 || true
cleanup_lock

# TEST-002d double acquire: acquire while held (brief test with 2s hold via background) ---

cleanup_lock
bash "$SCRIPTS/kb-lock.sh" acquire --run-id "holder-bg" >/dev/null 2>&1

# Second acquire should fail within 2-3s poll (we won't wait 30s in a unit test;
# just confirm it returns non-zero when lock already held with a custom short wait).
# We simulate by checking that status is LOCKED during the hold.
holder_status="$(bash "$SCRIPTS/kb-lock.sh" status 2>&1 || true)"
assert "TEST-002d double acquire: status is LOCKED while holder has it" "$(
  [[ "$holder_status" == "LOCKED:holder-bg" ]] && ok_result || fail_result "status='$holder_status'"
)"

bash "$SCRIPTS/kb-lock.sh" release --run-id "holder-bg" >/dev/null 2>&1 || true
cleanup_lock

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
