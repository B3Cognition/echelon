#!/usr/bin/env bash
# E2E: walk-up spec discovery — find_spec_dir via Python helper
set -uo pipefail
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
PYTHONPATH="$REPO_ROOT/src"

pass=0
fail=0
assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1)); printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1)); printf 'FAIL: %s — %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result()   { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
tmpdir="$(cd "$tmpdir" && pwd -P)"
trap 'rm -rf "$tmpdir"' EXIT

find_spec() {
  local spec_id="$1" start_dir="$2"
  PYTHONPATH="$PYTHONPATH" $PYTHON -c "
from pathlib import Path
from harness.spec_frontmatter import find_spec_dir
r = find_spec_dir('$spec_id', Path('$start_dir'))
print(r if r else 'None')
"
}

# ── Setup: P/specs/024-test/ and P/A/ (A has .git) ───────────────────────────
mkdir -p "$tmpdir/specs/024-test"
printf '# spec\n' > "$tmpdir/specs/024-test/spec.md"
mkdir -p "$tmpdir/A"
mkdir "$tmpdir/A/.git"

# ── Test 1: walk-up finds parent spec ─────────────────────────────────────────
result="$(find_spec 024 "$tmpdir/A")"
expected="$tmpdir/specs/024-test"
if [[ "$result" == "$expected" ]]; then
  assert "walk-up finds parent spec" "$(ok_result)"
else
  assert "walk-up finds parent spec" "$(fail_result " got: $result, expected: $expected")"
fi

# ── Test 2: local spec takes precedence ───────────────────────────────────────
mkdir -p "$tmpdir/A/specs/024-local"
printf '# local\n' > "$tmpdir/A/specs/024-local/spec.md"
result="$(find_spec 024 "$tmpdir/A")"
expected="$tmpdir/A/specs/024-local"
if [[ "$result" == "$expected" ]]; then
  assert "local spec takes precedence" "$(ok_result)"
else
  assert "local spec takes precedence" "$(fail_result " got: $result, expected: $expected")"
fi

# ── Test 3: stops when parent has .git ────────────────────────────────────────
mkdir "$tmpdir/.git"          # P now has .git
rm -rf "$tmpdir/A/specs/024-local"  # remove local so walk-up would be needed
result="$(find_spec 024 "$tmpdir/A")"
if [[ "$result" == "None" ]]; then
  assert "stops at git boundary in parent" "$(ok_result)"
else
  assert "stops at git boundary in parent" "$(fail_result " got: $result, expected None")"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "walk-up-spec-discovery smoke: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
