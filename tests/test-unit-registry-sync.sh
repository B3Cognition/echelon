#!/usr/bin/env bash
# Test: Agent registry vs prompt file sync check
# Verifies that every agent prompt file has an agents.yaml entry
# and every agents.yaml entry has a prompt file.
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Agent Registry Sync Test ==="

pass=0
fail=0

# Get registered agent files from agents.yaml
registered_files=$(grep -E '^\s+file:' "$REPO_ROOT/agents.yaml" | sed 's/.*file: *//' | sort)

# Get actual agent prompt files (exclude drafts/)
actual_files=$(find "$REPO_ROOT/agents" -name "*.md" -not -path "*/drafts/*" | \
  sed "s|$REPO_ROOT/||" | sort)

# Check for unregistered files
unregistered=$(comm -23 <(echo "$actual_files") <(echo "$registered_files"))
if [ -n "$unregistered" ]; then
  echo "FAIL: Unregistered agent files (exist but not in agents.yaml):"
  echo "$unregistered" | sed 's/^/  /'
  fail=$((fail + 1))
else
  echo "PASS: All agent files are registered"
  pass=$((pass + 1))
fi

# Check for missing files
missing=$(comm -13 <(echo "$actual_files") <(echo "$registered_files"))
if [ -n "$missing" ]; then
  echo "FAIL: Missing agent files (in agents.yaml but file not found):"
  echo "$missing" | sed 's/^/  /'
  fail=$((fail + 1))
else
  echo "PASS: All registered agents have prompt files"
  pass=$((pass + 1))
fi

reg_count=$(echo "$registered_files" | grep -c . || echo 0)
file_count=$(echo "$actual_files" | grep -c . || echo 0)
echo ""
echo "Registered: $reg_count | Files: $file_count"
echo "Results: $pass passed, $fail failed"

if [ $fail -gt 0 ]; then
  exit 1
fi
echo "ALL PASSED"
