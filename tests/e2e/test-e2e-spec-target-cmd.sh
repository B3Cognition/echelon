#!/usr/bin/env bash
# E2E: echelon spec target command — writes/replaces targets: frontmatter
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

# ── Test 1: write single target ───────────────────────────────────────────────
PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import os, sys
os.chdir('$tmpdir')
from echelon.cli import _cmd_spec_target
_cmd_spec_target(['024', 'og-platform'])
" > /dev/null 2>&1

result="$(PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import re, sys
sys.path.insert(0, '$REPO_ROOT/src')
from harness.spec_frontmatter import read_frontmatter
from pathlib import Path
data = read_frontmatter(Path('$tmpdir/specs/024-psd-import'))
print(data.get('targets', []))
")"
if [[ "$result" == "['og-platform']" ]]; then
  assert "single target written" "$(ok_result)"
else
  assert "single target written" "$(fail_result " got: $result")"
fi

# ── Test 2: replace with multiple targets ─────────────────────────────────────
PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import os, sys
os.chdir('$tmpdir')
from echelon.cli import _cmd_spec_target
_cmd_spec_target(['024', 'og-platform', 'fet-frontend-libs'])
" > /dev/null 2>&1

result="$(PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import sys
sys.path.insert(0, '$REPO_ROOT/src')
from harness.spec_frontmatter import read_frontmatter
from pathlib import Path
data = read_frontmatter(Path('$tmpdir/specs/024-psd-import'))
print(data.get('targets', []))
")"
if [[ "$result" == "['og-platform', 'fet-frontend-libs']" ]]; then
  assert "multiple targets written" "$(ok_result)"
else
  assert "multiple targets written" "$(fail_result " got: $result")"
fi

# ── Test 3: no duplication on rewrite ─────────────────────────────────────────
targets_count="$(grep -c 'targets:' "$tmpdir/specs/024-psd-import/spec.md" || true)"
if [[ "$targets_count" == "1" ]]; then
  assert "no duplication on rewrite" "$(ok_result)"
else
  assert "no duplication on rewrite" "$(fail_result " targets: appears $targets_count times")"
fi

# ── Test 4: ambiguous spec id exits non-zero, writes nothing ──────────────────
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
