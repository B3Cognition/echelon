#!/usr/bin/env bash
# T030: Integration — Pending Queue Merge Behavior
# Tests kb-pending-write.sh and kb-pending-merge.sh.
# Covers TEST-002d-3 (timeout queue creation) and TEST-002d-4 (idempotent merge).
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/runtime/scripts/bash"
FIXTURES="$REPO_ROOT/tests/fixtures/kb/valid-seeds"
PENDING_DIR="$REPO_ROOT/knowledge-base/.pending"

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

cleanup_pending() {
  rm -rf "$PENDING_DIR"
}
trap cleanup_pending EXIT

# TEST-002d-3: write 3 pending files, merge, assert all 3 entries in KB oldest-first ------

tmpdir="$(mktemp -d)"
test_kb="$tmpdir/estimates-log.yaml"
cp "$FIXTURES/estimates-log.yaml" "$test_kb"

cleanup_pending
mkdir -p "$PENDING_DIR"

# Write 3 pending entries with distinct operation IDs
for i in 1 2 3; do
  bash "$SCRIPTS/kb-pending-write.sh" \
    --target-file "$test_kb" \
    --operation append_entry \
    --payload "$(printf 'id: int-pending-%d\nagent: AUDITOR\ndomain: pending-test\nestimate_hours: %d\nconfidence: 0.5' "$i" "$i")" \
    --run-id "merge-run-001" \
    --agent "AUDITOR" \
    --operation-id "op-merge-00$i" >/dev/null
  # Small sleep to ensure different timestamps in filenames
  sleep 0.1
done

pending_count="$(find "$PENDING_DIR" -maxdepth 1 -name '*.pending.yaml' 2>/dev/null | wc -l | tr -d ' ')"
assert "INT-002d-3: 3 pending files created" "$(
  [[ "$pending_count" == "3" ]] && ok_result || fail_result "found $pending_count files"
)"

# Run merge
set +e
bash "$SCRIPTS/kb-pending-merge.sh" --run-id "merge-run-001"
merge_rc=$?
set -e

assert "INT-002d-3: kb-pending-merge.sh exits 0" "$(
  [[ "$merge_rc" == "0" ]] && ok_result || fail_result "exit $merge_rc"
)"
for i in 1 2 3; do
  assert "INT-002d-3: op-merge-00$i entry present in KB" "$(
    grep -q "operation_id: op-merge-00$i" "$test_kb" && ok_result || fail_result "op-merge-00$i missing"
  )"
done

# All pending files should be moved to processed/
remaining="$(find "$PENDING_DIR" -maxdepth 1 -name '*.pending.yaml' 2>/dev/null | wc -l | tr -d ' ')"
processed="$(find "$PENDING_DIR/processed" -name '*.pending.yaml' 2>/dev/null | wc -l | tr -d ' ')"
assert "INT-002d-3: no pending files remain after merge" "$(
  [[ "$remaining" == "0" ]] && ok_result || fail_result "$remaining files still pending"
)"
assert "INT-002d-3: 3 files in processed/" "$(
  [[ "$processed" == "3" ]] && ok_result || fail_result "found $processed in processed/"
)"

# TEST-002d-4: duplicate operation_id → only 1 entry in KB (idempotent) -------------------

cleanup_pending
mkdir -p "$PENDING_DIR"
test_kb2="$tmpdir/estimates-log-2.yaml"
cp "$FIXTURES/estimates-log.yaml" "$test_kb2"

# Write same operation_id twice
bash "$SCRIPTS/kb-pending-write.sh" \
  --target-file "$test_kb2" \
  --operation append_entry \
  --payload $'id: dedup-entry\nagent: AUDITOR\ndomain: dedup\nestimate_hours: 1\nconfidence: 0.5' \
  --run-id "dedup-run-001" \
  --agent "AUDITOR" \
  --operation-id "op-dedup-001" >/dev/null

bash "$SCRIPTS/kb-pending-write.sh" \
  --target-file "$test_kb2" \
  --operation append_entry \
  --payload $'id: dedup-entry\nagent: AUDITOR\ndomain: dedup\nestimate_hours: 1\nconfidence: 0.5' \
  --run-id "dedup-run-001" \
  --agent "AUDITOR" \
  --operation-id "op-dedup-001" >/dev/null

# Should only have 1 pending file despite 2 calls with same operation_id
dup_count="$(find "$PENDING_DIR" -maxdepth 1 -name '*op-dedup-001*' 2>/dev/null | wc -l | tr -d ' ')"
assert "INT-002d-4: duplicate operation_id produces only 1 pending file" "$(
  [[ "$dup_count" == "1" ]] && ok_result || fail_result "$dup_count files found"
)"

bash "$SCRIPTS/kb-pending-merge.sh" --run-id "dedup-run-001"

# Count entries with dedup id in KB
entry_count="$(grep -c 'operation_id: op-dedup-001' "$test_kb2" 2>/dev/null || echo 0)"
assert "INT-002d-4: only 1 entry for duplicate op-dedup-001 after merge" "$(
  [[ "$entry_count" == "1" ]] && ok_result || fail_result "$entry_count entries found"
)"

# TEST-002d checksum mismatch: one file corrupt → goes to failed/ -------------------------

cleanup_pending
mkdir -p "$PENDING_DIR"
test_kb3="$tmpdir/estimates-log-3.yaml"
cp "$FIXTURES/estimates-log.yaml" "$test_kb3"

# Write 2 good pending files
for i in 1 2; do
  bash "$SCRIPTS/kb-pending-write.sh" \
    --target-file "$test_kb3" \
    --operation append_entry \
    --payload "$(printf 'id: cksum-entry-%d\nagent: AUDITOR\ndomain: cksum\nestimate_hours: 1\nconfidence: 0.5' "$i")" \
    --run-id "cksum-run" \
    --agent "AUDITOR" \
    --operation-id "op-cksum-00$i" >/dev/null
done

# Write a 3rd and corrupt its checksum
bash "$SCRIPTS/kb-pending-write.sh" \
  --target-file "$test_kb3" \
  --operation append_entry \
  --payload $'id: corrupt-entry\nagent: AUDITOR\ndomain: cksum\nestimate_hours: 3\nconfidence: 0.3' \
  --run-id "cksum-run" \
  --agent "AUDITOR" \
  --operation-id "op-cksum-003" >/dev/null

# Find the 3rd pending file and corrupt its checksum field
pending_3="$(find "$PENDING_DIR" -maxdepth 1 -name '*op-cksum-003*' 2>/dev/null | head -1)"
if [[ -n "$pending_3" ]]; then
  sed 's/checksum: sha256:.*/checksum: sha256:deadbeefdeadbeef/' "$pending_3" > "${pending_3}.tmp"
  mv "${pending_3}.tmp" "$pending_3"
fi

bash "$SCRIPTS/kb-pending-merge.sh" --run-id "cksum-run" >/dev/null 2>/dev/null || true

assert "INT-002d cksum: good entries merged (op-cksum-001 present)" "$(
  grep -q 'operation_id: op-cksum-001' "$test_kb3" && ok_result || fail_result "op-cksum-001 missing"
)"
assert "INT-002d cksum: corrupt entry in failed/ not applied" "$(
  failed_count="$(find "$PENDING_DIR/failed" -name '*op-cksum-003*' 2>/dev/null | wc -l | tr -d ' ')"
  [[ "$failed_count" -ge 1 ]] && ok_result || fail_result "not in failed/: $failed_count"
)"
assert "INT-002d cksum: corrupt entry NOT in KB" "$(
  ! grep -q 'operation_id: op-cksum-003' "$test_kb3" \
    && ok_result || fail_result "corrupt entry was applied"
)"

rm -rf "$tmpdir"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
