#!/usr/bin/env bash
# T-28: Unit test — verify GUARDIAN always-on config in commander.md and guardian.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMMANDER="$ROOT/agents/control/commander.md"
GUARDIAN="$ROOT/agents/specialists/guardian.md"
SQUAD_RUN="$ROOT/commands/squad.run.md"
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

# Commander: guardian.mode config
assert_grep "$COMMANDER" "guardian.mode" "commander.md references guardian.mode config"
assert_grep "$COMMANDER" "always_on" "commander.md defines always_on mode"
assert_grep "$COMMANDER" "on_demand" "commander.md defines on_demand mode"
assert_grep "$COMMANDER" "Dispatch GUARDIAN" "commander.md has GUARDIAN dispatch section"
assert_grep "$COMMANDER" "Minimum Security Checklist" "commander.md references Minimum Security Checklist"
assert_grep "$COMMANDER" "guardian_dispatch_mode" "commander.md logs guardian_dispatch_mode in state.json"

# Guardian: always-on awareness
assert_grep "$GUARDIAN" "always_on" "guardian.md references always_on mode"
assert_grep "$GUARDIAN" "Minimum Security Checklist" "guardian.md has Minimum Security Checklist section"
assert_grep "$GUARDIAN" "guardian.mode" "guardian.md references guardian.mode config"
assert_grep "$GUARDIAN" "non-security domain" "guardian.md handles non-security domains"

# Squad run: updated summoning rules
assert_grep "$SQUAD_RUN" "always_on" "squad.run.md references always_on mode"
assert_grep "$SQUAD_RUN" "GUARDIAN" "squad.run.md references GUARDIAN codename"
assert_grep "$SQUAD_RUN" "guardian.mode" "squad.run.md references guardian.mode config"

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  echo "RESULT: PASS"
else
  echo "FAILURES: $FAILURES"
  echo "RESULT: FAIL"
  exit 1
fi
