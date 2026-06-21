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

# 1. echelon.run.md is a thin wrapper that delegates to the Python squad harness.
# After commit 448da9b the run.md→commander.md direct reference was replaced by harness
# delegation: run.md now says "delegates entirely to the Python squad harness (src/harness/squad.py)"
# and COMMANDER is dispatched by the harness only for judgment calls.
assert "echelon.run.md delegates to Python squad harness" \
  "grep -q 'squad.py\|squad harness' '$REPO_ROOT/extension/commands/echelon.run.md'"

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

# 6. Convergence rules — moved from commander.md to build-8-finalize.md in commit 448da9b.
# The harness now owns convergence enforcement; phase spec files carry the rules.
assert "build-8-finalize.md contains Convergence Rules" \
  "grep -q 'Convergence Rules' '$REPO_ROOT/extension/workflow/phases/build-8-finalize.md'"

# 7. commander.md contains meta-cognition checklist
assert "commander.md contains meta-cognition" \
  "grep -q 'Meta-Cognition' '$REPO_ROOT/extension/agents/control/commander.md'"

# 8. Token budget management — moved from commander.md to the harness (src/harness/squad.py,
# ralph.py) and phase spec (phase1-why2.md). phase1-why2.md carries the WHY iteration
# stop-condition table including the token_budget_k exhaustion condition.
assert "phase1-why2.md contains token_budget_k stop condition" \
  "grep -q 'token_budget_k\|token_budget_exhausted' '$REPO_ROOT/extension/workflow/phases/phase1-why2.md'"

# 9. echelon.run.md thin wrapper check — after commit 448da9b, run.md delegates to the
# Python harness (not directly to agents/control/commander.md). The harness dispatches
# COMMANDER only for judgment calls. Verify that COMMANDER is still referenced in run.md
# as a judgment-only agent (since run.md mentions "COMMANDER is dispatched only for judgment").
assert "echelon.run.md mentions COMMANDER judgment role" \
  "grep -q 'COMMANDER' '$REPO_ROOT/extension/commands/echelon.run.md'"

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
