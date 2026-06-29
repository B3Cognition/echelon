#!/usr/bin/env bash
# dry-run.sh — Validate the entire Echelon orchestration
# Usage: ./scripts/bash/dry-run.sh [path-to-repo-root-or-extension-root]
#
# Checks:
# 1. All agent files exist and are readable
# 2. agents.yaml is valid and complete
# 3. All commands exist
# 4. Config template is valid
# 5. Knowledge base is initialized
# 6. State machine flow is consistent
# 7. NEVER rules are present
# 8. Routing rules reference valid agents

set -euo pipefail

INPUT_ROOT="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
INPUT_ROOT="$(cd "$INPUT_ROOT" && pwd)"
if [ -f "$INPUT_ROOT/extension/extension.yml" ]; then
  REPO_ROOT="$INPUT_ROOT"
  EXT_ROOT="$INPUT_ROOT/extension"
elif [ -f "$INPUT_ROOT/extension.yml" ]; then
  EXT_ROOT="$INPUT_ROOT"
  REPO_ROOT="$(cd "$INPUT_ROOT/.." && pwd)"
else
  REPO_ROOT="$INPUT_ROOT"
  EXT_ROOT="$INPUT_ROOT/extension"
fi
PASS=0
FAIL=0
WARN=0

green() { printf "\033[32m✓\033[0m %s\n" "$1"; PASS=$((PASS + 1)); }
red()   { printf "\033[31m✗\033[0m %s\n" "$1"; FAIL=$((FAIL + 1)); }
yellow(){ printf "\033[33m⚠\033[0m %s\n" "$1"; WARN=$((WARN + 1)); }
header(){ printf "\n\033[1;36m═══ %s ═══\033[0m\n\n" "$1"; }

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║     ECHELON — DRY RUN VALIDATION         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Repository root: $REPO_ROOT"
echo "Extension root: $EXT_ROOT"

# ═══════════════════════════════════════════
header "1. AGENT FILES"
# ═══════════════════════════════════════════

AGENT_COUNT=0
for dir in control exploration feasibility solution specialists learning build; do
  if [ -d "$EXT_ROOT/agents/$dir" ]; then
    for f in "$EXT_ROOT/agents/$dir"/*.md; do
      if [ -f "$f" ]; then
        name=$(basename "$f" .md)
        size=$(wc -c < "$f" | tr -d ' ')
        if [ "$size" -gt 100 ]; then
          green "$dir/$name ($size bytes)"
        else
          red "$dir/$name — file too small ($size bytes), likely empty"
        fi
        AGENT_COUNT=$((AGENT_COUNT + 1))
      fi
    done
  else
    red "Directory agents/$dir/ not found"
  fi
done
echo ""
echo "  Agent files found: $AGENT_COUNT"

# ═══════════════════════════════════════════
header "2. AGENTS.YAML REGISTRY"
# ═══════════════════════════════════════════

if [ -f "$EXT_ROOT/agents.yaml" ]; then
  green "agents.yaml exists"

  # Validate YAML
  if python3 -c "import yaml; yaml.safe_load(open('$EXT_ROOT/agents.yaml'))" 2>/dev/null; then
    green "agents.yaml is valid YAML"
  else
    red "agents.yaml has YAML syntax errors"
  fi

  # Count agents in registry
  REG_COUNT=$(python3 -c "
import yaml
data = yaml.safe_load(open('$EXT_ROOT/agents.yaml'))
agents = data.get('agents', {})
print(len(agents))
" 2>/dev/null || echo "0")
  echo "  Agents in registry: $REG_COUNT"

  if [ "$REG_COUNT" -eq "$AGENT_COUNT" ] || [ "$REG_COUNT" -eq "$((AGENT_COUNT + 1))" ]; then
    green "Registry count matches file count ($REG_COUNT ≈ $AGENT_COUNT)"
  else
    yellow "Registry ($REG_COUNT) vs files ($AGENT_COUNT) — may include FEEDBACK"
  fi

  # Check every agent file reference exists
  python3 -c "
import yaml, os, sys
data = yaml.safe_load(open('$EXT_ROOT/agents.yaml'))
missing = []
for name, agent in data.get('agents', {}).items():
    f = agent.get('file', '')
    full = os.path.join('$EXT_ROOT', f)
    if not os.path.exists(full):
        missing.append(f'{name}: {f}')
if missing:
    for m in missing:
        print(f'MISSING: {m}')
    sys.exit(1)
else:
    print(f'ALL_EXIST:{len(data[\"agents\"])}')
" 2>/dev/null
  if [ $? -eq 0 ]; then
    green "All agent file references in registry point to existing files"
  else
    red "Some agent file references are broken"
  fi

  # Check NEVER rules
  NEVER_COUNT=$(python3 -c "
import yaml
data = yaml.safe_load(open('$EXT_ROOT/agents.yaml'))
count = sum(len(a.get('never', [])) for a in data.get('agents', {}).values())
print(count)
" 2>/dev/null || echo "0")
  echo "  NEVER rules defined: $NEVER_COUNT"
  if [ "$NEVER_COUNT" -gt 30 ]; then
    green "Sufficient NEVER rules ($NEVER_COUNT)"
  else
    yellow "Low NEVER rule count ($NEVER_COUNT) — some agents may lack constraints"
  fi

  # Check routing rules
  python3 -c "
import yaml
data = yaml.safe_load(open('$EXT_ROOT/agents.yaml'))
routing = data.get('routing', {})
agents = set(data.get('agents', {}).keys())
issues = []
for route_type, routes in routing.get('issue_routing', {}).items():
    if routes not in agents:
        issues.append(f'{route_type} -> {routes} (agent not in registry)')
for seq_name in ['build_sequence', 'phase_gate', 'final', 'continuous']:
    for agent in routing.get(seq_name, []):
        if agent not in agents:
            issues.append(f'{seq_name}: {agent} (agent not in registry)')
if issues:
    for i in issues:
        print(f'ROUTE_ERROR: {i}')
else:
    print('ROUTES_OK')
" 2>/dev/null
  ROUTE_CHECK=$?
  if [ $ROUTE_CHECK -eq 0 ]; then
    green "All routing rules reference valid agents"
  else
    red "Routing rules reference non-existent agents"
  fi

else
  yellow "agents.yaml removed — registry is now extension.yml (expected)"
fi

# ═══════════════════════════════════════════
header "3. COMMANDS"
# ═══════════════════════════════════════════

CMD_COUNT=0
for f in "$EXT_ROOT/commands"/*.md; do
  if [ -f "$f" ]; then
    name=$(basename "$f" .md)
    # Check frontmatter exists
    if head -1 "$f" | grep -q "^---"; then
      green "command: $name (has frontmatter)"
    else
      yellow "command: $name (missing YAML frontmatter)"
    fi
    CMD_COUNT=$((CMD_COUNT + 1))
  fi
done
echo ""
echo "  Commands found: $CMD_COUNT"

# Check extension.yml command references
if [ -f "$EXT_ROOT/extension.yml" ]; then
  EXT_CMDS=$(grep -c "file: \"commands/" "$EXT_ROOT/extension.yml" 2>/dev/null || echo "0")
  if [ "$EXT_CMDS" -eq "$CMD_COUNT" ]; then
    green "extension.yml registers all $CMD_COUNT commands"
  else
    yellow "extension.yml registers $EXT_CMDS commands but $CMD_COUNT exist"
  fi
fi

# ═══════════════════════════════════════════
header "4. EXTENSION MANIFEST"
# ═══════════════════════════════════════════

if [ -f "$EXT_ROOT/extension.yml" ]; then
  green "extension.yml exists"
  if python3 -c "import yaml; yaml.safe_load(open('$EXT_ROOT/extension.yml'))" 2>/dev/null; then
    green "extension.yml is valid YAML"
  else
    red "extension.yml has YAML syntax errors"
  fi

  # Check required fields
  for field in "id:" "name:" "version:" "description:" "speckit_version:"; do
    if grep -q "$field" "$EXT_ROOT/extension.yml"; then
      green "extension.yml has $field"
    else
      red "extension.yml missing $field"
    fi
  done
else
  red "extension.yml not found"
fi

# ═══════════════════════════════════════════
header "4B. WORKFLOW CONTRACT"
# ═══════════════════════════════════════════

if python3 - "$REPO_ROOT" "$EXT_ROOT" <<'PY'
from pathlib import Path
import sys

repo_root = Path(sys.argv[1]).resolve()
extension_root = Path(sys.argv[2]).resolve()
if not (extension_root / "workflow" / "definition.yaml").exists():
    print(f"workflow definition not found below {extension_root}")
    sys.exit(1)

src = repo_root / "src"
if src.exists():
    sys.path.insert(0, str(src))
sys.path.insert(0, str(repo_root))

try:
    from harness.workflow_validator import validate_workflow_definition
except Exception as exc:
    print(f"workflow validator unavailable: {exc}")
    sys.exit(1)

report = validate_workflow_definition(
    definition_path=extension_root / "workflow" / "definition.yaml",
    extension_yml_path=extension_root / "extension.yml",
)
if not report.ok:
    print(report.format())
    sys.exit(1)
print(report.format())
PY
then
  green "workflow definition contract is valid"
else
  red "workflow definition contract validation failed"
fi

# ═══════════════════════════════════════════
header "5. CONFIG TEMPLATE"
# ═══════════════════════════════════════════

if [ -f "$EXT_ROOT/config-template.yml" ]; then
  green "config-template.yml exists"
  if python3 -c "import yaml; yaml.safe_load(open('$EXT_ROOT/config-template.yml'))" 2>/dev/null; then
    green "config-template.yml is valid YAML"
    SECTIONS=$(python3 -c "
import yaml
data = yaml.safe_load(open('$EXT_ROOT/config-template.yml'))
print(len(data))
" 2>/dev/null || echo "0")
    echo "  Config sections: $SECTIONS"
  else
    red "config-template.yml has YAML syntax errors"
  fi
else
  red "config-template.yml not found"
fi

# ═══════════════════════════════════════════
header "6. KNOWLEDGE BASE"
# ═══════════════════════════════════════════

for f in patterns.yaml pitfalls.yaml calibration-profile.yaml estimates-log.yaml agent-scores.yaml; do
  if [ -f "$REPO_ROOT/knowledge-base/$f" ]; then
    if python3 -c "import yaml; yaml.safe_load(open('$REPO_ROOT/knowledge-base/$f'))" 2>/dev/null; then
      green "knowledge-base/$f (valid)"
    else
      red "knowledge-base/$f (invalid YAML)"
    fi
  else
    red "knowledge-base/$f not found"
  fi
done

# ═══════════════════════════════════════════
header "7. TEMPLATES"
# ═══════════════════════════════════════════

for f in state-schema.json evidence-grades.md context-pack.md kill-report.md feedback-questionnaire.md escalation-request.md; do
  if [ -f "$REPO_ROOT/templates/$f" ] || [ -f "$EXT_ROOT/templates/$f" ]; then
    green "templates/$f"
  else
    red "templates/$f not found"
  fi
done

# Check state-schema.json is valid JSON
if [ -f "$REPO_ROOT/templates/state-schema.json" ]; then
  if python3 -c "import json; json.load(open('$REPO_ROOT/templates/state-schema.json'))" 2>/dev/null; then
    green "state-schema.json is valid JSON"
  else
    red "state-schema.json has JSON syntax errors"
  fi
fi

# ═══════════════════════════════════════════
header "8. SCRIPTS"
# ═══════════════════════════════════════════

for f in detect-project.sh; do
  if [ -f "$EXT_ROOT/scripts/bash/$f" ]; then
    if [ -x "$EXT_ROOT/scripts/bash/$f" ]; then
      green "extension/scripts/bash/$f (executable)"
    else
      yellow "extension/scripts/bash/$f (not executable)"
    fi
  else
    red "extension/scripts/bash/$f not found"
  fi
done

for f in run-understanding.sh setup-worktree.sh migrate-kb.sh; do
  if [ -f "$REPO_ROOT/scripts/bash/$f" ] || [ -f "$EXT_ROOT/scripts/bash/$f" ]; then
    if [ -x "$REPO_ROOT/scripts/bash/$f" ] || [ -x "$EXT_ROOT/scripts/bash/$f" ]; then
      green "scripts/bash/$f (executable)"
    else
      yellow "scripts/bash/$f (not executable)"
    fi
  else
    red "scripts/bash/$f not found"
  fi
done

# ═══════════════════════════════════════════
header "9. STATE MACHINE FLOW SIMULATION"
# ═══════════════════════════════════════════

echo "  Simulating: INIT → SCOUT → SAGE1 → CARTOGRAPHER → SAGE2 → GATEKEEPER → ARCHITECT → ORCHESTRATOR → SAGE3 → FINALIZE"
echo ""

FLOW=(SCOUT SAGE CARTOGRAPHER SAGE GATEKEEPER ARCHITECT ORCHESTRATOR SAGE VALIDATOR)
FLOW_LABELS=("SCOUT (brownfield/greenfield)" "SAGE-WHY1 (assumption-challenge)" "CARTOGRAPHER (requirements)" "SAGE-WHY2 (spec-validation)" "GATEKEEPER (kill gate)" "ARCHITECT (architecture)" "ORCHESTRATOR (tasks)" "SAGE-WHY3 (consensus)" "VALIDATOR (backpropagation)")

for i in "${!FLOW[@]}"; do
  agent="${FLOW[$i]}"
  label="${FLOW_LABELS[$i]}"
  file=$(python3 -c "
import yaml
data = yaml.safe_load(open('$EXT_ROOT/extension.yml'))
codename_map = {}
for cmd in data.get('provides', {}).get('commands', []):
    n = cmd.get('name', '')
    f = cmd.get('file', '')
    if f.startswith('agents/'):
        short = n.split('.')[-1].upper().replace('-', '_')
        codename_map[short] = f
print(codename_map.get('$agent', 'NOT_FOUND'))
" 2>/dev/null || echo "NOT_FOUND")

  if [ -f "$EXT_ROOT/$file" ]; then
    green "Step $((i+1)): $label → $file"
  else
    red "Step $((i+1)): $label → $file (FILE NOT FOUND)"
  fi
done

echo ""
echo "  Build sequence:"
for agent in IMPLEMENTER SPEC_GUARD CODE_REVIEWER TEST_GUARDIAN; do
  file=$(python3 -c "
import yaml
data = yaml.safe_load(open('$EXT_ROOT/extension.yml'))
codename_map = {}
for cmd in data.get('provides', {}).get('commands', []):
    n = cmd.get('name', '')
    f = cmd.get('file', '')
    if f.startswith('agents/'):
        short = n.split('.')[-1].upper().replace('-', '_')
        codename_map[short] = f
print(codename_map.get('$agent', 'NOT_FOUND'))
" 2>/dev/null || echo "NOT_FOUND")

  if [ -f "$EXT_ROOT/$file" ]; then
    green "  Build: $agent → $file"
  else
    red "  Build: $agent → $file (FILE NOT FOUND)"
  fi
done

echo ""
echo "  Learning sequence:"
for agent in MIRROR ADAPTIVE AUDITOR REALIST; do
  file=$(python3 -c "
import yaml
data = yaml.safe_load(open('$EXT_ROOT/extension.yml'))
codename_map = {}
for cmd in data.get('provides', {}).get('commands', []):
    n = cmd.get('name', '')
    f = cmd.get('file', '')
    if f.startswith('agents/'):
        short = n.split('.')[-1].upper().replace('-', '_')
        codename_map[short] = f
print(codename_map.get('$agent', 'NOT_FOUND'))
" 2>/dev/null || echo "NOT_FOUND")

  if [ -f "$EXT_ROOT/$file" ]; then
    green "  Learn: $agent → $file"
  else
    red "  Learn: $agent → $file (FILE NOT FOUND)"
  fi
done

# ═══════════════════════════════════════════
header "10. ROLE SEPARATION VALIDATION"
# ═══════════════════════════════════════════

# Check that WHY agent has NEVER rewrite rules
if grep -q "NEVER rewrite" "$EXT_ROOT/agents/exploration/sage.md" 2>/dev/null; then
  green "WHY has NEVER-rewrite rules"
else
  red "WHY is missing NEVER-rewrite rules — ROLE VIOLATION RISK"
fi

# Check that IMPLEMENTER has NEVER modify specs rule
if grep -q "NEVER modify spec" "$EXT_ROOT/agents/build/implementer.md" 2>/dev/null; then
  green "IMPLEMENTER has NEVER-modify-specs rule"
else
  red "IMPLEMENTER missing NEVER-modify-specs — ROLE VIOLATION RISK"
fi

# Check that SPEC GUARD has NEVER fix code rule
if grep -q "NEVER fix code" "$EXT_ROOT/agents/build/spec-guard.md" 2>/dev/null; then
  green "SPEC GUARD has NEVER-fix-code rule"
else
  red "SPEC GUARD missing NEVER-fix-code — ROLE VIOLATION RISK"
fi

# Check thin wrapper delegates routing while COMMANDER owns role separation.
if grep -q "delegates entirely to the Python squad harness" "$EXT_ROOT/commands/echelon.run.md" 2>/dev/null \
  && grep -q "Phase routing is deterministic" "$EXT_ROOT/commands/echelon.run.md" 2>/dev/null; then
  green "run command delegates phase routing to the Python harness"
else
  red "run command does not document deterministic harness delegation"
fi

if grep -q "Role Separation" "$EXT_ROOT/agents/control/commander.md" 2>/dev/null; then
  green "COMMANDER agent has Role Separation protocol"
else
  red "COMMANDER missing Role Separation protocol — agents may cross roles"
fi

# ═══════════════════════════════════════════
header "11. ENFORCEMENT INFRASTRUCTURE"
# ═══════════════════════════════════════════

if [ -f "$EXT_ROOT/scripts/bash/pre-dispatch-gate.sh" ]; then
  if [ -x "$EXT_ROOT/scripts/bash/pre-dispatch-gate.sh" ]; then
    green "pre-dispatch-gate.sh exists and is executable"
  else
    yellow "pre-dispatch-gate.sh exists but not executable"
  fi
else
  yellow "pre-dispatch-gate.sh not found — enforcement not available"
fi

if [ -f "$EXT_ROOT/scripts/bash/post-execution-audit.sh" ]; then
  if [ -x "$EXT_ROOT/scripts/bash/post-execution-audit.sh" ]; then
    green "post-execution-audit.sh exists and is executable"
  else
    yellow "post-execution-audit.sh exists but not executable"
  fi
else
  yellow "post-execution-audit.sh not found — audit not available"
fi

# ═══════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║                    SUMMARY                        ║"
echo "╠══════════════════════════════════════════════════╣"
printf "║  \033[32m✓ PASS: %-3d\033[0m  \033[33m⚠ WARN: %-3d\033[0m  \033[31m✗ FAIL: %-3d\033[0m     ║\n" "$PASS" "$WARN" "$FAIL"
echo "╠══════════════════════════════════════════════════╣"

if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
  echo "║  🟢  ALL CHECKS PASSED — Squad ready to deploy   ║"
elif [ "$FAIL" -eq 0 ]; then
  echo "║  🟡  PASSED with warnings — review before deploy  ║"
else
  echo "║  🔴  FAILURES detected — fix before deploying      ║"
fi

echo "╚══════════════════════════════════════════════════╝"
echo ""

exit $FAIL
