#!/usr/bin/env bash
# E2E: orchestrator mode — prefixed output, parallel dispatch, exit code propagation
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
trap 'rm -rf "$tmpdir"' EXIT

ECHELON_YML=".echelon/config.yml"

# ── Setup: polyrepo P with spec and two initialised sub-repos ─────────────────
git -C "$tmpdir" init -q  # workspace root must be a git repo for harness run
mkdir -p "$tmpdir/specs/024-test"
printf -- "---\ntargets:\n  - repo-a\n  - repo-b\n---\n# spec\n" \
  > "$tmpdir/specs/024-test/spec.md"
PYTHONPATH="$PYTHONPATH" SPEC_DIR="$tmpdir/specs/024-test" "$PYTHON" <<'PY'
import os
from pathlib import Path
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS

spec_dir = Path(os.environ["SPEC_DIR"])
for artifact in REQUIRED_PHASE_A_BUILD_INPUTS:
    path = spec_dir / artifact
    if path.exists() or artifact in {"spec.md", "tasks.md", "constitution.md"}:
        continue
    if artifact == "plan-conformance.json":
        path.write_text(
            '{\n'
            '  "status": "pass",\n'
            '  "findings": [],\n'
            '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
            '}\n',
            encoding="utf-8",
        )
    else:
        path.write_text(f"# {artifact}\n", encoding="utf-8")
PY
cat > "$tmpdir/specs/024-test/tasks.md" <<'TASKS'
- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none target=repo-a

  **Files:**
  - `repo-a/src/main.py` - repo-a implementation

- [ ] T-002 complexity=standard phase=build req=FR-002 depends=none target=repo-b

  **Files:**
  - `repo-b/src/main.py` - repo-b implementation
TASKS
printf '# Constitution\n\nPrinciples are defined for this project.\n' \
  > "$tmpdir/specs/024-test/constitution.md"

for repo in repo-a repo-b; do
  mkdir -p "$tmpdir/$repo/$(dirname $ECHELON_YML)"
  printf 'harness:\n  target_repo: .\n' > "$tmpdir/$repo/$ECHELON_YML"
  git -C "$tmpdir/$repo" init -q  # polyrepo targets must be git repos (validate_targets)
done

# ── Stub: canonical delivery child that echoes and exits 0 ───────────────────
mkdir -p "$tmpdir/bin"
cat > "$tmpdir/bin/echelon" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == "delivery" && "$2" == "run" ]]; then
    echo "hello from $(basename "$(pwd)")"
    exit 0
fi
STUB
chmod +x "$tmpdir/bin/echelon"

run_orchestrator() {
  local stub_exit="${1:-0}"
  # Rewrite stub exit for repo-b
  cat > "$tmpdir/bin/echelon" <<STUB
#!/usr/bin/env bash
if [[ "\$1" == "delivery" && "\$2" == "run" ]]; then
    repo="\$(basename "\$(pwd)")"
    echo "output from \$repo"
    if [[ "\$repo" == "repo-b" && "$stub_exit" != "0" ]]; then exit 1; fi
    exit 0
fi
STUB
  chmod +x "$tmpdir/bin/echelon"

  PATH="$tmpdir/bin:$PATH" PYTHONPATH="$PYTHONPATH" $PYTHON -c "
import os, sys
os.chdir('$tmpdir')
sys.argv = ['echelon', 'harness', 'run', '024']
from echelon.cli import main
try:
    main()
except SystemExit as e:
    sys.exit(e.code or 0)
"
}

# ── Test 1: both succeed → output prefixed, exit 0 ───────────────────────────
run_orchestrator 0 > "$tmpdir/out_success.txt" 2>&1
success_rc=$?

if grep -q '\[repo-a\]' "$tmpdir/out_success.txt" && \
   grep -q '\[repo-b\]' "$tmpdir/out_success.txt"; then
  assert "output contains [repo-a] and [repo-b] prefixes" "$(ok_result)"
else
  assert "output contains [repo-a] and [repo-b] prefixes" \
    "$(fail_result " output: $(cat "$tmpdir/out_success.txt")")"
fi

if [[ "$success_rc" -eq 0 ]]; then
  assert "both succeed → exit 0" "$(ok_result)"
else
  assert "both succeed → exit 0" "$(fail_result " exit code: $success_rc")"
fi

# ── Test 2: one failure → both outputs appear, exit 1 ────────────────────────
run_orchestrator 1 > "$tmpdir/out_fail.txt" 2>&1
fail_rc=$?

if grep -q '\[repo-a\]' "$tmpdir/out_fail.txt" && \
   grep -q '\[repo-b\]' "$tmpdir/out_fail.txt"; then
  assert "both outputs appear even when one fails" "$(ok_result)"
else
  assert "both outputs appear even when one fails" \
    "$(fail_result " output: $(cat "$tmpdir/out_fail.txt")")"
fi

if [[ "$fail_rc" -ne 0 ]]; then
  assert "one failure → exit 1" "$(ok_result)"
else
  assert "one failure → exit 1" "$(fail_result " expected non-zero, got 0")"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "orchestrator-prefixed-output smoke: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
