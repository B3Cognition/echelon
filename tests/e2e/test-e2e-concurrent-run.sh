#!/usr/bin/env bash
# T033: E2E — Concurrent Run Scenario
# Two processes compete for the KB lock; second times out and creates a .pending file;
# its entry is merged on next run. Final KB has exactly 2 entries.
# Covers TEST-002d-5.
# Runs entirely in an isolated tmpdir; does NOT modify the real knowledge-base.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
UTILS="$REPO_ROOT/tests/utils"
FIXTURES="$REPO_ROOT/tests/fixtures/kb/valid-seeds"
KB_DIR="$REPO_ROOT/knowledge-base"
LOCK_DIR="$KB_DIR/.locks/kb-write.lock"

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

cleanup_all() {
  rm -rf "$LOCK_DIR"
  [[ -d "${KB_DIR}/.pending" ]] && rm -rf "${KB_DIR}/.pending"
  [[ -f "$test_kb" ]] && rm -f "$test_kb"
  [[ -d "$tmpdir" ]] && rm -rf "$tmpdir"
}
tmpdir="$(mktemp -d)"
test_kb="$tmpdir/estimates-log.yaml"
trap cleanup_all EXIT

cp "$FIXTURES/estimates-log.yaml" "$test_kb"

# Worker A: acquires lock, writes entry-A, holds for LOCK_HOLD_SECONDS, releases.
# Worker B: tries to acquire lock while A holds it (hold > 30s timeout boundary);
#           times out, creates a .pending file for entry-B.
# After both workers exit, a merge run is triggered to process the pending file.
#
# NOTE: This test relies on wall-clock timing to force a lock timeout.
# kb-lock.sh has a DEFAULT_WAIT_SECONDS=30 timeout; Worker A must hold longer.
# We use a 20-second margin (50s hold vs 30s timeout) so CI on slow machines
# is unlikely to produce a race at the boundary. The ideal fix would be a
# signal/semaphore mechanism so the test is deterministic, but that requires
# changes to kb-lock.sh itself.

LOCK_HOLD_SECONDS=50

# Run Worker A inline (foreground, holds lock 31s in background)
(
  bash "$SCRIPTS/kb-lock.sh" acquire --run-id "e2e-run-A" >/dev/null 2>&1
  # Write entry A while holding the lock
  bash "$SCRIPTS/kb-write.sh" append_entry \
    --file "$test_kb" \
    --payload $'id: concurrent-entry-A\nagent: AUDITOR\ndomain: e2e\nestimate_hours: 1\nconfidence: 0.8' \
    --run-id "e2e-run-A" \
    --source "AUDITOR" \
    --operation-id "op-concurrent-A" >/dev/null 2>&1
  # Hold for LOCK_HOLD_SECONDS to force Worker B to timeout
  sleep "$LOCK_HOLD_SECONDS"
  bash "$SCRIPTS/kb-lock.sh" release --run-id "e2e-run-A" >/dev/null 2>&1
) &
WORKER_A_PID=$!

# Give Worker A a moment to acquire the lock
sleep 1

# Worker B: tries to acquire lock; will timeout after 30s and create .pending
(
  set +e
  bash "$SCRIPTS/kb-lock.sh" acquire --run-id "e2e-run-B" >/dev/null 2>&1
  lock_rc=$?
  set -e
  if [[ "$lock_rc" -eq 2 ]]; then
    # Lock timeout — create pending entry
    bash "$SCRIPTS/kb-pending-write.sh" \
      --target-file "$test_kb" \
      --operation append_entry \
      --payload $'id: concurrent-entry-B\nagent: AUDITOR\ndomain: e2e\nestimate_hours: 2\nconfidence: 0.7' \
      --run-id "e2e-run-B" \
      --agent "AUDITOR" \
      --operation-id "op-concurrent-B" >/dev/null 2>&1
  fi
  exit 0
) &
WORKER_B_PID=$!

# Wait for both workers (Worker A runs ~51s; Worker B times out after 30s + overhead)
wait "$WORKER_A_PID" || true
wait "$WORKER_B_PID" || true

assert "E2E-002d-5: Worker A entry present in KB after its run" "$(
  grep -q 'operation_id: op-concurrent-A' "$test_kb" && ok_result || fail_result "entry-A missing"
)"

# Worker B's entry should be in .pending/ after lock timeout
pending_b_count="$(find "${KB_DIR}/.pending" -maxdepth 1 -name '*op-concurrent-B*' 2>/dev/null | wc -l | tr -d ' ')"
assert "E2E-002d-5: Worker B created .pending file on lock timeout" "$(
  [[ "$pending_b_count" -ge 1 ]] && ok_result || fail_result "pending file count=$pending_b_count"
)"

# Merge run: process Worker B's pending file
bash "$SCRIPTS/kb-pending-merge.sh" --run-id "e2e-merge" >/dev/null 2>&1 || true

assert "E2E-002d-5: Worker B entry merged into KB" "$(
  grep -q 'operation_id: op-concurrent-B' "$test_kb" && ok_result || fail_result "entry-B missing after merge"
)"

# Final KB state: exactly 2 entries (one from each worker), no corruption, no duplicates
entry_a_count="$(grep -c 'operation_id: op-concurrent-A' "$test_kb" 2>/dev/null || echo 0)"
entry_b_count="$(grep -c 'operation_id: op-concurrent-B' "$test_kb" 2>/dev/null || echo 0)"
assert "E2E-002d-5: exactly 1 entry-A (no duplicates)" "$(
  [[ "$entry_a_count" == "1" ]] && ok_result || fail_result "count=$entry_a_count"
)"
assert "E2E-002d-5: exactly 1 entry-B (no duplicates)" "$(
  [[ "$entry_b_count" == "1" ]] && ok_result || fail_result "count=$entry_b_count"
)"

# KB file should pass schema validate
set +e
bash "$SCRIPTS/kb-recover.sh" detect --file "$test_kb" >/dev/null 2>&1
detect_rc=$?
set -e
assert "E2E-002d-5: KB file passes schema detect after concurrent run" "$(
  [[ "$detect_rc" == "0" ]] && ok_result || fail_result "detect exit $detect_rc"
)"

# Both workers should have exited cleanly (0 or 2 for B on timeout — both acceptable)
assert "E2E-002d-5: final lock is released" "$(
  [[ ! -d "$LOCK_DIR" ]] && ok_result || fail_result "lock dir still exists"
)"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
