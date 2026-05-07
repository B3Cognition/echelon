#!/usr/bin/env bash
# Test: Extension.yml registry vs prompt file sync check
# Verifies that every agent prompt file has an extension.yml entry
# and every extension.yml agent entry has a prompt file.
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Agent Registry Sync Test (extension.yml) ==="

pass=0
fail=0

# Get agent file paths from extension.yml (entries under provides/commands with file: agents/...)
registered_files=$(python3 -c "
import yaml, sys
data = yaml.safe_load(open('$REPO_ROOT/extension/extension.yml'))
for cmd in data.get('provides', {}).get('commands', []):
    f = cmd.get('file', '')
    if f.startswith('agents/'):
        print('extension/' + f)
" | sort)

# Get actual agent prompt files (exclude .gitkeep)
actual_files=$(find "$REPO_ROOT/extension/agents" -name "*.md" -not -name ".gitkeep" | \
  sed "s|$REPO_ROOT/||" | sort)

# Check for unregistered files
unregistered=$(comm -23 <(echo "$actual_files") <(echo "$registered_files"))
if [ -n "$unregistered" ]; then
  echo "FAIL: Unregistered agent files (exist but not in extension.yml):"
  echo "$unregistered" | sed 's/^/  /'
  fail=$((fail + 1))
else
  echo "PASS: All agent files are registered in extension.yml"
  pass=$((pass + 1))
fi

# Check for missing files
missing=$(comm -13 <(echo "$actual_files") <(echo "$registered_files"))
if [ -n "$missing" ]; then
  echo "FAIL: Missing agent files (in extension.yml but file not found):"
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
