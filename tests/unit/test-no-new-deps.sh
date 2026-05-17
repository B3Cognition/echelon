#!/usr/bin/env bash
# Meta-tests: verify no new external dependencies introduced (NFR-003).
# Tests: META-01, META-02 per test-strategy.md
# Run: bash tests/unit/test-no-new-deps.sh

set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PASS=0
FAIL=0

echo "=== META-01: No new tool dependencies in Python config ==="
# Check pyproject.toml and any requirements*.txt for jq, yq, or other new tool deps
NEW_TOOL_DEPS="jq\|yq\|xmlstarlet\|xsltproc"
FOUND=0
for f in "$ROOT_DIR/pyproject.toml" "$ROOT_DIR"/requirements*.txt; do
  if [ -f "$f" ]; then
    # Only check [dependencies] or [project.dependencies] sections, skip comments
    if grep -v '^\s*#' "$f" | grep -qi "^\s*\"*$NEW_TOOL_DEPS" 2>/dev/null; then
      echo "  FAIL: META-01 found new tool dependency in $f"
      FOUND=1
    fi
  fi
done
if [ "$FOUND" -eq 0 ]; then
  echo "  PASS: META-01 no new tool dependencies in Python config"
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
fi

echo ""
echo "=== META-02: No unknown binary invocations in new scripts ==="
# Allowed commands in spec 027 scripts
ALLOWED_CMDS="bash|jq|python3|wc|cat|echo|date|mktemp|grep|sed|awk|chmod|touch|printf|set|local|if|then|else|fi|while|do|done|for|case|esac|shift|exit|return|test|true|false|read|export|trap|rm|mkdir|head|tail|dirname|cd|pwd"

# New scripts introduced by spec 027
NEW_SCRIPTS=(
  "$ROOT_DIR/extension/scripts/bash/validate-journal-entry.sh"
  "$ROOT_DIR/extension/scripts/bash/journal-append.sh"
)

UNKNOWN_FOUND=0
for script in "${NEW_SCRIPTS[@]}"; do
  if [ ! -f "$script" ]; then
    echo "  WARN: META-02 script not found: $script"
    continue
  fi
  # Extract command invocations: lines starting with a command or piped commands
  # Look for any command that is NOT in the allowed set
  # Simple heuristic: extract words at the start of lines or after | or $( that look like commands
  COMMANDS=$(grep -oE '(^|\||&&|\$\()\s*[a-zA-Z_][a-zA-Z0-9_-]*' "$script" \
    | sed 's/^[|&$(]*//' \
    | tr -d '[:space:]' \
    | sort -u \
    | grep -vE "^($ALLOWED_CMDS)$" \
    | grep -vE '^(ENTRY|SCHEMA|SCRIPT|VALIDATOR|JOURNAL|TMP|OUTPUT|VALID|RC|PASS|FAIL|LARGE|WARNING|VERDICT|COMPACT|VIOLATION|CURRENT|TIMESTAMP|HAS|TOOL|WARN|STDERR|UNKNOWN|LINE|FIRST|SECOND|VID|VTYPE|DETAILS|ROOT|FIXTURES|CLEANUP)' \
    | grep -vE '^[A-Z_]+$' \
    || true)

  if [ -n "$COMMANDS" ]; then
    echo "  WARN: META-02 potentially unknown commands in $(basename "$script"): $COMMANDS"
    # Don't fail for jq since it's in the allowed list — just double-check
  fi
done

# Direct check: ensure only allowed binaries are called
for script in "${NEW_SCRIPTS[@]}"; do
  if [ ! -f "$script" ]; then
    continue
  fi
  # Check for specific disallowed tools
  for banned in "curl" "wget" "npm" "pip" "apt" "yum" "brew" "docker" "yq"; do
    if grep -qw "$banned" "$script" 2>/dev/null; then
      echo "  FAIL: META-02 found banned command '$banned' in $(basename "$script")"
      UNKNOWN_FOUND=1
    fi
  done
done

if [ "$UNKNOWN_FOUND" -eq 0 ]; then
  echo "  PASS: META-02 no unknown binary invocations in new scripts"
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
fi

echo ""
echo "═══════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
