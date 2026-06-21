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

assert_eq() {
  local actual="$1" expected="$2" label="$3"
  if [ "$actual" = "$expected" ]; then
    echo "PASS: $label"
    pass=$((pass + 1))
  else
    echo "FAIL: $label (expected '$expected', got '$actual')"
    fail=$((fail + 1))
  fi
}

# Get agent file paths from extension.yml (entries under provides/commands with file: agents/...)
registered_files=$(python3 -c "
import yaml, sys
data = yaml.safe_load(open('$REPO_ROOT/extension/extension.yml'))
for cmd in data.get('provides', {}).get('commands', []):
    f = cmd.get('file', '')
    if f.startswith('agents/'):
        print('extension/' + f)
" | sort)

# Get actual agent prompt files (exclude .gitkeep, appendices/, and templates/
# which are reference docs extracted from agents, not agent entry points).
actual_files=$(find "$REPO_ROOT/extension/agents" -name "*.md" -not -name ".gitkeep" \
  -not -path "*/appendices/*" -not -path "*/templates/*" | \
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

# ── Re-* workflow externalization assertions ─────────────────────────────────

# 1. All 13 re-* phase nodes registered in definition.yaml
RE_PHASE_COUNT=$(python3 -c "
import yaml, sys
d = yaml.safe_load(open('$REPO_ROOT/extension/workflow/definition.yaml'))
phases = (
    [p['id'] for p in d.get('re_extraction', {}).get('phases', [])] +
    [p['id'] for p in d.get('re_retarget', {}).get('phases', [])] +
    [p['id'] for p in d.get('re_planning', {}).get('phases', [])]
)
print(len(phases))
" 2>/dev/null || echo "0")
assert_eq "$RE_PHASE_COUNT" "13" "re-* phase nodes in definition.yaml"

# 2. All type:agent phases in re-* sections reference an existing agents/re/ file
RE_AGENT_FILE_CHECK=$(python3 -c "
import yaml, os, sys
d = yaml.safe_load(open('$REPO_ROOT/extension/workflow/definition.yaml'))
missing = []
for section in ['re_extraction', 're_planning']:
    for phase in d.get(section, {}).get('phases', []):
        if phase.get('type') == 'agent':
            name = phase['agent'].split('-re-')[1] if '-re-' in phase['agent'] else None
            if name:
                f = '$REPO_ROOT/extension/agents/re/' + name + '.md'
                if not os.path.exists(f):
                    missing.append(f)
print(len(missing))
" 2>/dev/null || echo "999")
assert_eq "$RE_AGENT_FILE_CHECK" "0" "all re-* agent phases have agent files"

# 3. 9 new re-* agent entries in extension.yml
RE_AGENT_ENTRY_COUNT=$(python3 -c "
import yaml
d = yaml.safe_load(open('$REPO_ROOT/extension/extension.yml'))
agents = [c for c in d['provides']['commands']
          if 're-' in c['name'] and c.get('behavior', {}).get('execution') == 'agent']
print(len(agents))
" 2>/dev/null || echo "0")
assert_eq "$RE_AGENT_ENTRY_COUNT" "9" "re-* agent entries in extension.yml"

# 4. All 12 re-* command entries have no behavior block
RE_NEUTRAL_CMD_COUNT=$(python3 -c "
import yaml
d = yaml.safe_load(open('$REPO_ROOT/extension/extension.yml'))
neutral = [c for c in d['provides']['commands']
           if 're-' in c['name']
           and c.get('behavior', {}).get('execution') != 'agent'
           and 'behavior' not in c]
print(len(neutral))
" 2>/dev/null || echo "0")
assert_eq "$RE_NEUTRAL_CMD_COUNT" "12" "all 12 re-* commands have no behavior block"

reg_count=$(echo "$registered_files" | grep -c . || echo 0)
file_count=$(echo "$actual_files" | grep -c . || echo 0)
echo ""
echo "Registered: $reg_count | Files: $file_count"
echo "Results: $pass passed, $fail failed"

if [ $fail -gt 0 ]; then
  exit 1
fi
echo "ALL PASSED"
