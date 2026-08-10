#!/usr/bin/env bash
# Regression tests for state helper runtime path overrides.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/runtime/scripts/bash"

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
run_dir="$tmpdir/runs/run-state"
mkdir -p "$run_dir"
cat > "$run_dir/state.json" <<'JSON'
{
  "phase": "unit",
  "status": "active"
}
JSON

backup_path="$(ECHELON_RUN_DIR="$run_dir" bash "$SCRIPTS/state-backup.sh" 2>/dev/null)"
assert "state-backup defaults to active run dir state.json" "$(
  [[ "$backup_path" == "$run_dir"/backups/state-unit-*.json && -f "$backup_path" ]] && ok_result || fail_result "backup_path=$backup_path"
)"

lock_output="$(ECHELON_RUN_DIR="$run_dir" bash "$SCRIPTS/state-lock.sh" acquire --run-id run-state 2>&1)"
assert "state-lock writes lock into active run dir" "$(
  [[ "$lock_output" == "ACQUIRED" && -f "$run_dir/.state.lock" && -f "$run_dir/.state.lock.meta" ]] && ok_result || fail_result "$lock_output"
)"

ECHELON_RUN_DIR="$run_dir" bash "$SCRIPTS/state-lock.sh" release --run-id run-state >/dev/null 2>&1
assert "state-lock releases active run dir lock" "$(
  [[ ! -f "$run_dir/.state.lock" && ! -f "$run_dir/.state.lock.meta" ]] && ok_result || fail_result "lock remains"
)"

rm -rf "$tmpdir"

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
