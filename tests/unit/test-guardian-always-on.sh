#!/usr/bin/env bash
# T-28: Unit test — verify GUARDIAN always-on config in commander.md and guardian.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMMANDER="$ROOT/extension/agents/control/commander.md"
GUARDIAN="$ROOT/extension/agents/specialists/guardian.md"
SQUAD_RUN="$ROOT/extension/workflow/phases/phase3-specialists.md"
FAILURES=0

assert_grep() {
  local file="$1"
  local pattern="$2"
  local description="$3"
  local filename
  filename=$(basename "$file")
  if grep -q "$pattern" "$file"; then
    echo "PASS: [$filename] $description"
  else
    echo "FAIL: [$filename] $description (pattern: $pattern)"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "=== GUARDIAN Always-On Unit Tests ==="
echo ""

# Commander: guardian.mode config — slim commander.md still holds the
# guardian.mode key reference; the detailed dispatch content (always_on,
# on_demand, GUARDIAN Dispatch Mode, Minimum Security Checklist,
# guardian_dispatch_mode) was extracted to phase3-specialists.md.
assert_grep "$COMMANDER" "guardian.mode" "commander.md references guardian.mode config"
assert_grep "$SQUAD_RUN" "always_on" "phase3-specialists.md defines always_on mode"
assert_grep "$SQUAD_RUN" "on_demand" "phase3-specialists.md defines on_demand mode"
assert_grep "$SQUAD_RUN" "SECURITY Dispatch" "phase3-specialists.md has GUARDIAN dispatch section"
assert_grep "$SQUAD_RUN" "Minimum Security Checklist" "phase3-specialists.md references Minimum Security Checklist"
assert_grep "$SQUAD_RUN" "guardian.mode" "phase3-specialists.md references guardian.mode (dispatch control key)"

# Guardian: always-on awareness
assert_grep "$GUARDIAN" "always_on" "guardian.md references always_on mode"
assert_grep "$GUARDIAN" "Minimum Security Checklist" "guardian.md has Minimum Security Checklist section"
assert_grep "$GUARDIAN" "guardian.mode" "guardian.md references guardian.mode config"
assert_grep "$GUARDIAN" "non-security domain" "guardian.md handles non-security domains"

# Squad run: updated summoning rules
assert_grep "$SQUAD_RUN" "always_on" "echelon.run.md references always_on mode"
assert_grep "$SQUAD_RUN" "GUARDIAN" "echelon.run.md references GUARDIAN codename"
assert_grep "$SQUAD_RUN" "guardian.mode" "echelon.run.md references guardian.mode config"

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  echo "RESULT: PASS"
else
  echo "FAILURES: $FAILURES"
  echo "RESULT: FAIL"
  exit 1
fi
