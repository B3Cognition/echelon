#!/usr/bin/env bash
# Regression tests for small runtime utilities using active squad dirs.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"

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
squad_dir="$tmpdir/runs/run-runtime"
mkdir -p "$squad_dir"

ECHELON_SQUAD_DIR="$squad_dir" bash "$REPO_ROOT/scripts/bash/lida_broadcast.sh" broadcast '{"message":"ok"}'
assert "lida_broadcast writes payload under active squad dir" "$(
  [[ -f "$squad_dir/lida-payload.json" ]] && grep -q '"message":"ok"' "$squad_dir/lida-payload.json" && ok_result || fail_result "payload missing"
)"

ECHELON_SQUAD_DIR="$squad_dir" bash "$REPO_ROOT/scripts/bash/lida_broadcast.sh" cleanup run-runtime
assert "lida_broadcast cleanup removes active squad payload" "$(
  [[ ! -f "$squad_dir/lida-payload.json" ]] && ok_result || fail_result "payload remains"
)"

rm -rf "$tmpdir"

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
