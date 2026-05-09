#!/usr/bin/env bash
# Test: COMMANDER prompt loading regression test
# Verifies that echelon.run.md and echelon.build.md reference commander.md
# and that commander.md contains required decision frameworks.
# Prevents regression of the bug fixed in commit 8bbeb9f.
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/.." && pwd)"

pass=0
fail=0
errors=""

assert() {
  local desc="$1" cmd="$2"
  if eval "$cmd" >/dev/null 2>&1; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    errors="${errors}\n  FAIL: $desc"
  fi
}

echo "=== COMMANDER Loading Regression Test ==="

# 1. echelon.run.md references commander.md
assert "echelon.run.md references commander.md" \
  "grep -q 'commander.md' '$REPO_ROOT/extension/commands/echelon.run.md'"

# 2. echelon.build.md references commander.md
assert "echelon.build.md references commander.md" \
  "grep -q 'commander.md' '$REPO_ROOT/extension/commands/echelon.build.md'"

# 3. commander.md contains Evidence Hierarchy
assert "commander.md contains Evidence Hierarchy" \
  "grep -q 'Evidence Hierarchy' '$REPO_ROOT/extension/agents/control/commander.md'"

# 4. commander.md contains EVOI
assert "commander.md contains EVOI" \
  "grep -q 'EVOI' '$REPO_ROOT/extension/agents/control/commander.md'"

# 5. commander.md contains Toulmin
assert "commander.md contains Toulmin" \
  "grep -q 'Toulmin' '$REPO_ROOT/extension/agents/control/commander.md'"

# 6. commander.md contains convergence rules
assert "commander.md contains convergence rules" \
  "grep -q 'Convergence Rules' '$REPO_ROOT/extension/agents/control/commander.md'"

# 7. commander.md contains meta-cognition checklist
assert "commander.md contains meta-cognition" \
  "grep -q 'Meta-Cognition' '$REPO_ROOT/extension/agents/control/commander.md'"

# 8. commander.md contains token budget
assert "commander.md contains token budget management" \
  "grep -q 'Token Budget' '$REPO_ROOT/extension/agents/control/commander.md'"

# 9. echelon.run.md delegates to commander.md (thin wrapper check)
assert "echelon.run.md delegates to agents/control/commander.md" \
  "grep -q 'agents/control/commander.md' '$REPO_ROOT/extension/commands/echelon.run.md'"

# 10. echelon.build.md delegates to commander.md (thin wrapper check)
# NOTE: the "MANDATORY FIRST STEP" heading was intentionally removed in commit a0519d2
# when echelon.build.md was refactored into a thin phase-delegating wrapper.
assert "echelon.build.md references agents/control/commander.md" \
  "grep -q 'agents/control/commander.md' '$REPO_ROOT/extension/commands/echelon.build.md'"

# 11. No SCIENTIST references in commander.md (ISS-001 fix)
assert "commander.md has no SCIENTIST references (use INVESTIGATOR)" \
  "! grep -q 'SCIENTIST' '$REPO_ROOT/extension/agents/control/commander.md'"

# 12. INVESTIGATOR referenced in Evidence Hierarchy
assert "commander.md Evidence Hierarchy uses INVESTIGATOR" \
  "grep -q 'INVESTIGATOR' '$REPO_ROOT/extension/agents/control/commander.md'"

echo ""
echo "Results: $pass passed, $fail failed"
if [ $fail -gt 0 ]; then
  echo -e "$errors"
  exit 1
fi
echo "ALL PASSED"
