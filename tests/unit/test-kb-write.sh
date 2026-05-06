#!/usr/bin/env bash
# T025: Unit tests — Story 002c Mutation Metadata
# Tests kb-write.sh append_entry metadata injection and validate_append_only.
set -uo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
FIXTURES="$REPO_ROOT/tests/fixtures/kb/valid-seeds"

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
  "$@" >/dev/null
  _rc=$?
  set -e
  echo "$_rc"
}

# TEST-002c-1: append_entry injects created_at, run_id, source even when omitted ----------

tmpdir="$(mktemp -d)"
test_kb="$tmpdir/estimates-log.yaml"
cp "$FIXTURES/estimates-log.yaml" "$test_kb"

rc="$(run_cmd bash "$SCRIPTS/kb-write.sh" append_entry \
  --file "$test_kb" \
  --payload $'id: test-entry-001\nagent: AUDITOR\ndomain: testing\nestimate_hours: 1\nconfidence: 0.9' \
  --run-id "test-run-001" \
  --operation-id "op-unit-001")"

assert "TEST-002c-1: append_entry exits 0" "$(
  [[ "$rc" == "0" ]] && ok_result || fail_result "exit $rc"
)"
assert "TEST-002c-1: created_at injected into entry" "$(
  grep -q 'created_at:' "$test_kb" && ok_result || fail_result "created_at not found"
)"
assert "TEST-002c-1: run_id injected into entry" "$(
  grep -q 'run_id: test-run-001' "$test_kb" && ok_result || fail_result "run_id not found"
)"
assert "TEST-002c-1: source injected into entry" "$(
  grep -q 'source:' "$test_kb" && ok_result || fail_result "source not found"
)"
assert "TEST-002c-1: operation_id present in entry" "$(
  grep -q 'operation_id: op-unit-001' "$test_kb" && ok_result || fail_result "operation_id not found"
)"
# Verify created_at is ISO-8601 format
assert "TEST-002c-1: created_at is ISO-8601 format" "$(
  grep 'created_at:' "$test_kb" | grep -q '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T' \
    && ok_result || fail_result "$(grep 'created_at:' "$test_kb")"
)"

# TEST-002c (atomic): no .tmp files remain after successful write --------------------------

tmp_count="$(find "$tmpdir" -name '*.tmp.*' 2>/dev/null | wc -l | tr -d ' ')"
assert "TEST-002c: no temp files after successful write" "$(
  [[ "$tmp_count" == "0" ]] && ok_result || fail_result "$tmp_count temp files found"
)"

# TEST-002c-3: validate_append_only detects removed entry → KB_APPEND_ONLY_VIOLATION -------

# First, write a baseline so the checksum store is initialised for this file.
rc_base="$(run_cmd bash "$SCRIPTS/kb-write.sh" validate_append_only --file "$test_kb")"
# (Baseline write may return 0 on first call; that is expected.)

# Append a second entry to update the baseline
bash "$SCRIPTS/kb-write.sh" append_entry \
  --file "$test_kb" \
  --payload $'id: test-entry-002\nagent: AUDITOR\ndomain: testing\nestimate_hours: 2\nconfidence: 0.7' \
  --run-id "test-run-001" \
  --operation-id "op-unit-002" >/dev/null 2>&1 || true

# Update baseline again
bash "$SCRIPTS/kb-write.sh" validate_append_only --file "$test_kb" >/dev/null 2>&1 || true

# Now destructively remove a line containing one of the entries (simulate corruption/deletion)
$PYTHON - "$test_kb" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
lines = p.read_text(encoding="utf-8").splitlines()
# Remove the block starting with "  - operation_id: op-unit-001" through the next empty line or next "- "
new_lines = []
skip = False
for line in lines:
    if "operation_id: op-unit-001" in line:
        skip = True
    if skip and (line.strip() == "" or (line.startswith("  - ") and "operation_id: op-unit-001" not in line)):
        skip = False
    if not skip:
        new_lines.append(line)
p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
PY

set +e
bash "$SCRIPTS/kb-write.sh" validate_append_only --file "$test_kb" 2>/tmp/val_stderr_$$
val_rc=$?
set -e
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

assert "TEST-002c-3: validate_append_only exits non-zero on removed entry" "$(
  [[ "$val_rc" -ne 0 ]] && ok_result || fail_result "exit 0 (should be non-zero)"
)"
assert "TEST-002c-3: KB_APPEND_ONLY_VIOLATION in stderr" "$(
  grep -q 'KB_APPEND_ONLY_VIOLATION' /tmp/val_stderr_$$ 2>/dev/null \
    && ok_result || fail_result "$(cat /tmp/val_stderr_$$ 2>/dev/null)"
)"

rm -f /tmp/val_stderr_$$
rm -rf "$tmpdir"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
