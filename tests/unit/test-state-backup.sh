#!/usr/bin/env bash
# test-state-backup.sh — Verify state-backup.sh backup creation, rotation, and phase naming
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/bash/state-backup.sh"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== State Backup Tests ==="
echo ""

# Setup temp directory
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# --- Script exists and is executable ---
echo "--- Script existence ---"

if [[ -f "$SCRIPT" ]]; then
  pass "state-backup.sh exists"
else
  fail "state-backup.sh does not exist"
fi

if [[ -x "$SCRIPT" ]]; then
  pass "state-backup.sh is executable"
else
  fail "state-backup.sh is not executable"
fi

# --- No state file: exits cleanly ---
echo ""
echo "--- Missing state file ---"

OUTPUT=$("$SCRIPT" "$TMPDIR/nonexistent.json" 2>&1) || true
if [[ "$OUTPUT" == *"No state file to backup"* ]]; then
  pass "Exits cleanly when state file missing"
else
  fail "Did not handle missing state file: $OUTPUT"
fi

# --- Basic backup creation ---
echo ""
echo "--- Basic backup creation ---"

STATE_FILE="$TMPDIR/state.json"
cat > "$STATE_FILE" <<'EJSON'
{
  "phase": "understand",
  "status": "active",
  "token_ledger": { "total_estimated_tokens": 5000 }
}
EJSON

BACKUP_PATH=$("$SCRIPT" "$STATE_FILE" 5)

if [[ -f "$BACKUP_PATH" ]]; then
  pass "Backup file created"
else
  fail "Backup file not created: $BACKUP_PATH"
fi

if [[ "$BACKUP_PATH" == *"state-understand-"* ]]; then
  pass "Backup filename contains phase name 'understand'"
else
  fail "Backup filename missing phase name: $BACKUP_PATH"
fi

if [[ "$BACKUP_PATH" == *".json" ]]; then
  pass "Backup filename ends with .json"
else
  fail "Backup filename does not end with .json: $BACKUP_PATH"
fi

BACKUP_DIR="$(dirname "$STATE_FILE")/backups"
if [[ -d "$BACKUP_DIR" ]]; then
  pass "Backups directory created"
else
  fail "Backups directory not created"
fi

# Verify content matches
if diff -q "$STATE_FILE" "$BACKUP_PATH" >/dev/null 2>&1; then
  pass "Backup content matches original"
else
  fail "Backup content does not match original"
fi

# --- Phase extraction for different phase names ---
echo ""
echo "--- Phase extraction ---"

cat > "$STATE_FILE" <<'EJSON'
{
  "phase": "build",
  "status": "active"
}
EJSON

BACKUP_PATH=$("$SCRIPT" "$STATE_FILE" 5)
if [[ "$BACKUP_PATH" == *"state-build-"* ]]; then
  pass "Phase 'build' correctly extracted"
else
  fail "Phase 'build' not extracted: $BACKUP_PATH"
fi

# --- Unknown phase (no phase field) ---
echo ""
echo "--- Unknown phase handling ---"

cat > "$STATE_FILE" <<'EJSON'
{
  "status": "active"
}
EJSON

BACKUP_PATH=$("$SCRIPT" "$STATE_FILE" 5)
if [[ "$BACKUP_PATH" == *"state-unknown-"* ]]; then
  pass "Missing phase defaults to 'unknown'"
else
  fail "Missing phase did not default to 'unknown': $BACKUP_PATH"
fi

# --- Rotation: keep only MAX_BACKUPS ---
echo ""
echo "--- Backup rotation ---"

# Clean the backups directory
rm -rf "$BACKUP_DIR"

# Create state with phase
cat > "$STATE_FILE" <<'EJSON'
{
  "phase": "decide",
  "status": "active"
}
EJSON

# Create 7 backups with max 3
for i in $(seq 1 7); do
  sleep 1  # ensure different timestamps
  "$SCRIPT" "$STATE_FILE" 3 >/dev/null
done

BACKUP_COUNT=$(ls "$BACKUP_DIR"/state-*.json 2>/dev/null | wc -l | tr -d ' ')
if [[ "$BACKUP_COUNT" -le 3 ]]; then
  pass "Rotation keeps at most 3 backups (found $BACKUP_COUNT)"
else
  fail "Rotation failed: found $BACKUP_COUNT backups (expected <= 3)"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
