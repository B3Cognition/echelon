#!/usr/bin/env bash
# E2E: echelon spec target command — refuses post-hoc target mutation.
# Runs in isolated tmpdir; uses Python module directly (no installed binary needed).
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

run_spec_target() {
  PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import os, sys
os.chdir('$1')
sys.argv = ['echelon', 'spec', 'target'] + $2
from echelon.cli import _cmd_spec_target
try:
    _cmd_spec_target(sys.argv[3:])
except SystemExit as e:
    sys.exit(e.code or 0)
" 2>/dev/null
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

# ── Setup ─────────────────────────────────────────────────────────────────────
mkdir -p "$tmpdir/specs/024-psd-import"
printf '# PSD Import Spec\n' > "$tmpdir/specs/024-psd-import/spec.md"

# ── Test 1: target mutation is rejected and writes no metadata ────────────────
set +e
target_output="$(PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import os, sys
os.chdir('$tmpdir')
from echelon.cli import _cmd_spec_target
_cmd_spec_target(['024', 'og-platform'])
" 2>&1)"
target_rc=$?
set -e

if [[ "$target_rc" -eq 2 ]]; then
  assert "post-hoc target mutation exits 2" "$(ok_result)"
else
  assert "post-hoc target mutation exits 2" "$(fail_result " rc=$target_rc output=$target_output")"
fi

if [[ "$target_output" == *"no longer mutates generated specifications"* ]]; then
  assert "post-hoc target mutation explains replacement workflow" "$(ok_result)"
else
  assert "post-hoc target mutation explains replacement workflow" "$(fail_result " output=$target_output")"
fi

if [[ ! -e "$tmpdir/specs/024-psd-import/targets.yml" ]]; then
  assert "post-hoc target mutation writes no targets.yml" "$(ok_result)"
else
  assert "post-hoc target mutation writes no targets.yml" "$(fail_result " targets.yml exists")"
fi

# ── Test 2: ambiguous spec id still writes nothing ────────────────────────────
mkdir -p "$tmpdir/specs/024-alpha"
printf '# alpha\n' > "$tmpdir/specs/024-alpha/spec.md"

set +e
PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import os, sys
os.chdir('$tmpdir')
from echelon.cli import _cmd_spec_target
_cmd_spec_target(['024', 'og-platform'])
" > /dev/null 2>&1
ambig_rc=$?
set -e
. "$(cd "$(dirname -- "$0")/.." && pwd)/utils/python-detect.sh"

alpha_has_targets="$(PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import sys
sys.path.insert(0, '$REPO_ROOT/src')
from harness.spec_frontmatter import read_frontmatter
from pathlib import Path
data = read_frontmatter(Path('$tmpdir/specs/024-alpha'))
print('targets' in data)
" 2>/dev/null || echo False)"

if [[ "$ambig_rc" -ne 0 && "$alpha_has_targets" == "False" ]]; then
  assert "ambiguous id exits 1, writes nothing" "$(ok_result)"
else
  assert "ambiguous id exits 1, writes nothing" "$(fail_result " rc=$ambig_rc written=$alpha_has_targets")"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "spec-target-cmd smoke: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
