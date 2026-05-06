#!/usr/bin/env bash
# T023: Unit tests — Story 002a Schema Validation Gate
# Tests kb-recover.sh detect and kb-seed.sh initialization.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
FIXTURES="$REPO_ROOT/tests/fixtures/kb"
VALID_SEEDS="$FIXTURES/valid-seeds"
CORRUPTED="$FIXTURES/corrupted"

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

# TEST-002a-1: schema gate with valid fixtures passes (exit 0) -------------------------

for fixture in estimates-log.yaml patterns.yaml pitfalls.yaml calibration-profile.yaml; do
  rc="$(run_cmd bash "$SCRIPTS/kb-recover.sh" detect --file "$VALID_SEEDS/$fixture")"
  assert "TEST-002a-1: detect on valid $fixture exits 0" "$(
    [[ "$rc" == "0" ]] && ok_result || fail_result "exit $rc"
  )"
done

# TEST-002a-1 (negative): schema gate with schema-invalid.yaml exits 1 with KB_SCHEMA_INVALID

tmpdir="$(mktemp -d)"
ERROR_LOG_BACKUP="${REPO_ROOT}/.specify/squad/error.log"
[[ -f "$ERROR_LOG_BACKUP" ]] && cp "$ERROR_LOG_BACKUP" "$tmpdir/error.log.bak"
: > "$ERROR_LOG_BACKUP" 2>/dev/null || true

# Copy as estimates-log.yaml so the full required-fields set is applied
cp "$CORRUPTED/schema-invalid.yaml" "$tmpdir/estimates-log.yaml"
rc="$(run_cmd bash "$SCRIPTS/kb-recover.sh" detect --file "$tmpdir/estimates-log.yaml")"
assert "TEST-002a-1(neg): schema-invalid.yaml exits 1" "$(
  [[ "$rc" == "1" ]] && ok_result || fail_result "exit $rc"
)"
assert "TEST-002a-1(neg): KB_SCHEMA_INVALID in stderr/error.log" "$(
  grep -q 'KB_SCHEMA_INVALID' "${REPO_ROOT}/.specify/squad/error.log" 2>/dev/null \
    && ok_result || fail_result "KB_SCHEMA_INVALID not found in error.log"
)"

[[ -f "$tmpdir/error.log.bak" ]] && cp "$tmpdir/error.log.bak" "$ERROR_LOG_BACKUP" || true

# TEST-002a-2: kb-seed.sh initializes all 4 KB files, all pass detect check ---------------

tmpdir2="$(mktemp -d)"
# We need to simulate an empty knowledge-base for kb-seed.sh.
# Since kb-seed.sh uses hardcoded REPO_ROOT paths, we back up and restore KB files.
KB_DIR="$REPO_ROOT/knowledge-base"
KB_FILES=(calibration-profile.yaml estimates-log.yaml patterns.yaml pitfalls.yaml)
BACKUP_DIR="$tmpdir2/kb_backup"
mkdir -p "$BACKUP_DIR"

# Step 1: Backup current KB files (only those that exist)
for f in "${KB_FILES[@]}"; do
  target="$KB_DIR/$f"
  if [[ -f "$target" ]]; then
    cp "$target" "$BACKUP_DIR/$f"
  fi
done

# Step 2: Remove KB files to simulate empty state
for f in "${KB_FILES[@]}"; do
  rm -f "$KB_DIR/$f"
done

# Step 3: Run kb-seed.sh
rc_seed="$(run_cmd bash "$SCRIPTS/kb-seed.sh")"
assert "TEST-002a-2: kb-seed.sh exits 0 on empty KB" "$(
  [[ "$rc_seed" == "0" ]] && ok_result || fail_result "exit $rc_seed"
)"

# Step 4: Verify all 4 files created and pass detect
for f in "${KB_FILES[@]}"; do
  target="$KB_DIR/$f"
  assert "TEST-002a-2: $f created by kb-seed.sh" "$(
    [[ -f "$target" ]] && ok_result || fail_result "file not found"
  )"
  if [[ -f "$target" ]]; then
    rc_det="$(run_cmd bash "$SCRIPTS/kb-recover.sh" detect --file "$target")"
    assert "TEST-002a-2: $f passes detect after seed" "$(
      [[ "$rc_det" == "0" ]] && ok_result || fail_result "detect exit $rc_det"
    )"
  fi
done

# Step 5: Restore original KB files
for f in "${KB_FILES[@]}"; do
  if [[ -f "$BACKUP_DIR/$f" ]]; then
    cp "$BACKUP_DIR/$f" "$KB_DIR/$f"
  else
    rm -f "$KB_DIR/$f"
  fi
done

rm -rf "$tmpdir" "$tmpdir2"

# TEST-002a-3: validate schema_version and entries keys in seeded files --------------------

for fixture in estimates-log.yaml patterns.yaml pitfalls.yaml; do
  has_schema="$(grep -c 'schema_version:' "$VALID_SEEDS/$fixture" 2>/dev/null || echo 0)"
  has_entries="$(grep -c 'entries:' "$VALID_SEEDS/$fixture" 2>/dev/null || echo 0)"
  assert "TEST-002a-3: $fixture has schema_version key" "$(
    [[ "$has_schema" -gt 0 ]] && ok_result || fail_result "schema_version missing"
  )"
  assert "TEST-002a-3: $fixture has entries key" "$(
    [[ "$has_entries" -gt 0 ]] && ok_result || fail_result "entries missing"
  )"
done

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
