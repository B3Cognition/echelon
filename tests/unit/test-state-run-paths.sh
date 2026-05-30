#!/usr/bin/env bash
# Regression tests for state helper runtime path overrides.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"

pass=0
fail=0

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1))
    printf 'FAIL: %s - %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result() { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
squad_dir="$tmpdir/runs/run-state"
mkdir -p "$squad_dir"
cat > "$squad_dir/state.json" <<'JSON'
{
  "phase": "unit",
  "status": "active"
}
JSON

backup_path="$(ECHELON_SQUAD_DIR="$squad_dir" bash "$SCRIPTS/state-backup.sh" 2>/dev/null)"
assert "state-backup defaults to active squad dir state.json" "$(
  [[ "$backup_path" == "$squad_dir"/backups/state-unit-*.json && -f "$backup_path" ]] && ok_result || fail_result "backup_path=$backup_path"
)"

lock_output="$(ECHELON_SQUAD_DIR="$squad_dir" bash "$SCRIPTS/state-lock.sh" acquire --run-id run-state 2>&1)"
assert "state-lock writes lock into active squad dir" "$(
  [[ "$lock_output" == "ACQUIRED" && -f "$squad_dir/.state.lock" && -f "$squad_dir/.state.lock.meta" ]] && ok_result || fail_result "$lock_output"
)"

ECHELON_SQUAD_DIR="$squad_dir" bash "$SCRIPTS/state-lock.sh" release --run-id run-state >/dev/null 2>&1
assert "state-lock releases active squad dir lock" "$(
  [[ ! -f "$squad_dir/.state.lock" && ! -f "$squad_dir/.state.lock.meta" ]] && ok_result || fail_result "lock remains"
)"

rm -rf "$tmpdir"

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
