#!/usr/bin/env bash
# T024: Unit tests — Story 002b Corruption Error Codes
# Tests kb-recover.sh detect and backup subcommands.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/runtime/scripts/bash"
FIXTURES="$REPO_ROOT/tests/fixtures/kb"
VALID_SEEDS="$FIXTURES/valid-seeds"
CORRUPTED="$FIXTURES/corrupted"
RECOVERY_DIR="$REPO_ROOT/runs/recovery"
ERROR_LOG="$REPO_ROOT/runs/error.log"

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

reset_error_log() {
  mkdir -p "$(dirname "$ERROR_LOG")"
  [[ -f "$ERROR_LOG" ]] && cp "$ERROR_LOG" "${ERROR_LOG}.bak.$$" || true
  : > "$ERROR_LOG"
}
restore_error_log() {
  if [[ -f "${ERROR_LOG}.bak.$$" ]]; then
    mv "${ERROR_LOG}.bak.$$" "$ERROR_LOG"
  else
    rm -f "$ERROR_LOG"
  fi
}
trap restore_error_log EXIT

# TEST-002b-1: detect on malformed.yaml → exit 1, KB_SCHEMA_INVALID with file path ---------

reset_error_log
rc="$(run_cmd bash "$SCRIPTS/kb-recover.sh" detect --file "$CORRUPTED/malformed.yaml")"
assert "TEST-002b-1: detect on malformed.yaml exits 1" "$(
  [[ "$rc" == "1" ]] && ok_result || fail_result "exit $rc"
)"
assert "TEST-002b-1: KB_SCHEMA_INVALID in error.log with file path" "$(
  grep -q "KB_SCHEMA_INVALID.*malformed.yaml" "$ERROR_LOG" 2>/dev/null \
    && ok_result || fail_result "$(cat "$ERROR_LOG")"
)"

# TEST-002b-1: violated field name is included in error message ---------------------------

reset_error_log
bash "$SCRIPTS/kb-recover.sh" detect --file "$CORRUPTED/malformed.yaml" 2>&1 || true
# The error message should mention a field name (not just the file path)
assert "TEST-002b-1: error message includes violated field name" "$(
  grep -qE 'KB_SCHEMA_INVALID.*:.*:' "$ERROR_LOG" 2>/dev/null \
    && ok_result || fail_result "field name not in: $(cat "$ERROR_LOG")"
)"

# TEST-002b-2: backup creates timestamped file in RECOVERY_DIR ---------------------------

tmpdir="$(mktemp -d)"
test_file="$tmpdir/estimates-log.yaml"
cp "$VALID_SEEDS/estimates-log.yaml" "$test_file"

backup_path="$(bash "$SCRIPTS/kb-recover.sh" backup --file "$test_file" 2>/dev/null)"
assert "TEST-002b-2: backup returns non-empty path" "$(
  [[ -n "$backup_path" ]] && ok_result || fail_result "backup_path is empty"
)"
assert "TEST-002b-2: backup file exists" "$(
  [[ -f "$backup_path" ]] && ok_result || fail_result "file $backup_path not found"
)"
# Check ISO-8601 timestamp pattern in filename (contains digits with T separator)
assert "TEST-002b-2: backup filename has ISO-8601-like timestamp" "$(
  # Timestamp is formatted YYYY-MM-DDTHH-MM-SSZ in backup path (colons replaced)
  [[ "$backup_path" =~ [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2} ]] \
    && ok_result || fail_result "filename=$backup_path"
)"
# Verify backup content matches source
assert "TEST-002b-2: backup content matches original" "$(
  diff -q "$test_file" "$backup_path" >/dev/null 2>&1 && ok_result || fail_result "content differs"
)"

# TEST-002b (negative): detect on valid fixture → exit 0, no KB_SCHEMA_INVALID -------------

reset_error_log
rc2="$(run_cmd bash "$SCRIPTS/kb-recover.sh" detect --file "$VALID_SEEDS/estimates-log.yaml")"
assert "TEST-002b-neg: detect on valid fixture exits 0" "$(
  [[ "$rc2" == "0" ]] && ok_result || fail_result "exit $rc2"
)"
assert "TEST-002b-neg: no KB_SCHEMA_INVALID in error.log for valid fixture" "$(
  ! grep -q 'KB_SCHEMA_INVALID' "$ERROR_LOG" 2>/dev/null \
    && ok_result || fail_result "unexpected KB_SCHEMA_INVALID in error.log"
)"

rm -rf "$tmpdir"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
