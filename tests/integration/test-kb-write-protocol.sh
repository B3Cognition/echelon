#!/usr/bin/env bash
# T029: Integration — KB Write Protocol + Corruption Recovery
# Full write roundtrip: seed → write via lock → validate append-only.
# Corruption → backup → restore → recovery_mode=true.
# Covers TEST-002a-2, TEST-002b-2, TEST-002b-3, TEST-002c-2, TEST-002c-3, TEST-002d-4.
set -uo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
FIXTURES="$REPO_ROOT/tests/fixtures/kb"
VALID_SEEDS="$FIXTURES/valid-seeds"
CORRUPTED="$FIXTURES/corrupted"
KB_DIR="$REPO_ROOT/knowledge-base"
LOCK_DIR="$KB_DIR/.locks/kb-write.lock"
STATE_FILE="$REPO_ROOT/.specify/squad/state.json"
ERROR_LOG="$REPO_ROOT/.specify/squad/error.log"

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
  # Restore state.json if we backed it up
  if [[ -f "${STATE_FILE}.bak.$$" ]]; then
    mv "${STATE_FILE}.bak.$$" "$STATE_FILE"
  fi
  if [[ -f "${ERROR_LOG}.bak.$$" ]]; then
    mv "${ERROR_LOG}.bak.$$" "$ERROR_LOG"
  fi
}
trap cleanup_all EXIT

mkdir -p "$(dirname "$STATE_FILE")" "$(dirname "$ERROR_LOG")"
[[ -f "$STATE_FILE" ]] && cp "$STATE_FILE" "${STATE_FILE}.bak.$$"
[[ -f "$ERROR_LOG" ]] && cp "$ERROR_LOG" "${ERROR_LOG}.bak.$$" || true
: > "$ERROR_LOG"

# TEST-002a-2 + TEST-002c-2: full write roundtrip via lock ---------------------------------

tmpdir="$(mktemp -d)"
test_kb="$tmpdir/estimates-log.yaml"
cp "$VALID_SEEDS/estimates-log.yaml" "$test_kb"

set +e
bash "$SCRIPTS/kb-lock.sh" acquire --run-id "int-run-001"
lock_rc=$?
set -e
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

assert "INT write roundtrip: lock acquired" "$(
  [[ "$lock_rc" == "0" ]] && ok_result || fail_result "acquire exit $lock_rc"
)"

if [[ "$lock_rc" == "0" ]]; then
  # Write entry while holding lock
  bash "$SCRIPTS/kb-write.sh" append_entry \
    --file "$test_kb" \
    --payload $'id: int-entry-001\nagent: AUDITOR\ndomain: integration\nestimate_hours: 2\nconfidence: 0.85' \
    --run-id "int-run-001" \
    --source "AUDITOR" \
    --operation-id "op-int-001" >/dev/null

  # Release lock
  bash "$SCRIPTS/kb-lock.sh" release --run-id "int-run-001"
fi

assert "INT write roundtrip: entry present in KB file" "$(
  grep -q 'operation_id: op-int-001' "$test_kb" && ok_result || fail_result "entry not found"
)"
assert "INT write roundtrip: lock released" "$(
  [[ ! -d "$LOCK_DIR" ]] && ok_result || fail_result "lock still held"
)"
assert "INT write roundtrip: no temp files in tmpdir" "$(
  count="$(find "$tmpdir" -name '*.tmp.*' 2>/dev/null | wc -l | tr -d ' ')"
  [[ "$count" == "0" ]] && ok_result || fail_result "$count temp files found"
)"

# Validate append-only after write
bash "$SCRIPTS/kb-write.sh" validate_append_only --file "$test_kb" >/dev/null 2>/dev/null || true

# TEST-002c-3: append-only rejection on destructive rewrite -----------------------------

# Write second entry, update baseline
bash "$SCRIPTS/kb-write.sh" append_entry \
  --file "$test_kb" \
  --payload $'id: int-entry-002\nagent: AUDITOR\ndomain: integration\nestimate_hours: 1\nconfidence: 0.7' \
  --run-id "int-run-001" \
  --source "AUDITOR" \
  --operation-id "op-int-002" >/dev/null
bash "$SCRIPTS/kb-write.sh" validate_append_only --file "$test_kb" >/dev/null 2>/dev/null || true

# Destructively truncate the file (simulate deletion attack)
printf 'schema_version: 1\nappend_only: true\nentries: []\n' > "$test_kb"

set +e
bash "$SCRIPTS/kb-write.sh" validate_append_only --file "$test_kb" 2>/tmp/aov_stderr_$$
aov_rc=$?
set -e
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

assert "INT-002c-3: validate_append_only rejects destructive rewrite (non-zero)" "$(
  [[ "$aov_rc" -ne 0 ]] && ok_result || fail_result "exit 0 (should fail)"
)"
assert "INT-002c-3: KB_APPEND_ONLY_VIOLATION in stderr" "$(
  grep -q 'KB_APPEND_ONLY_VIOLATION' /tmp/aov_stderr_$$ 2>/dev/null \
    && ok_result || fail_result "$(cat /tmp/aov_stderr_$$ 2>/dev/null)"
)"
rm -f /tmp/aov_stderr_$$

# TEST-002b-2 + TEST-002b-3: corruption → backup → restore → recovery_mode ----------------

tmpdir2="$(mktemp -d)"
corrupt_kb="$tmpdir2/estimates-log.yaml"
cp "$CORRUPTED/malformed.yaml" "$corrupt_kb"

# backup
backup_path="$(bash "$SCRIPTS/kb-recover.sh" backup --file "$corrupt_kb" 2>/dev/null)"
assert "INT-002b-2: backup created for corrupted file" "$(
  [[ -f "$backup_path" ]] && ok_result || fail_result "backup_path=$backup_path"
)"

# restore: since no valid backup exists for corrupt_kb, it will use the seed fixture
printf '{"run_id":"int-test"}\n' > "$STATE_FILE"
set +e
bash "$SCRIPTS/kb-recover.sh" restore --file "$corrupt_kb" >/dev/null 2>&1
restore_rc=$?
set -e
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

assert "INT-002b-3: restore exits 0" "$(
  [[ "$restore_rc" == "0" ]] && ok_result || fail_result "exit $restore_rc"
)"
# Verify restored file passes detect
set +e
bash "$SCRIPTS/kb-recover.sh" detect --file "$corrupt_kb" >/dev/null 2>&1
detect_rc=$?
set -e
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"
assert "INT-002b-3: restored file passes detect" "$(
  [[ "$detect_rc" == "0" ]] && ok_result || fail_result "detect exit $detect_rc"
)"
# Verify recovery_mode=true in state.json
rcm="$($PYTHON -c "import json; d=json.load(open('$STATE_FILE')); print(d.get('recovery_mode', False))" 2>/dev/null || echo false)"
assert "INT-002b-3: recovery_mode=true in state.json after restore" "$(
  [[ "$rcm" == "True" ]] && ok_result || fail_result "recovery_mode=$rcm"
)"

rm -rf "$tmpdir" "$tmpdir2"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
