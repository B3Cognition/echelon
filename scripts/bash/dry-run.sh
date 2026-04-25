#!/usr/bin/env bash
# dry-run.sh — Validate the entire Echelon orchestration
# Usage: ./scripts/bash/dry-run.sh [path-to-extension-root]
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

ROOT="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
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
echo "Extension root: $ROOT"

# ═══════════════════════════════════════════
header "1. AGENT FILES"
# ═══════════════════════════════════════════

AGENT_COUNT=0
for dir in control exploration feasibility solution specialists learning build; do
  if [ -d "$ROOT/agents/$dir" ]; then
    for f in "$ROOT/agents/$dir"/*.md; do
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

if [ -f "$ROOT/extension/agents.yaml" ]; then
  green "agents.yaml exists"

  # Validate YAML
  if python3 -c "import yaml; yaml.safe_load(open('$ROOT/extension/agents.yaml'))" 2>/dev/null; then
    green "agents.yaml is valid YAML"
  else
    red "agents.yaml has YAML syntax errors"
  fi

  # Count agents in registry
  REG_COUNT=$(python3 -c "
import yaml
data = yaml.safe_load(open('$ROOT/extension/agents.yaml'))
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
data = yaml.safe_load(open('$ROOT/extension/agents.yaml'))
missing = []
for name, agent in data.get('agents', {}).items():
    f = agent.get('file', '')
    full = os.path.join('$ROOT', f)
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
data = yaml.safe_load(open('$ROOT/extension/agents.yaml'))
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
data = yaml.safe_load(open('$ROOT/extension/agents.yaml'))
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
  red "agents.yaml not found"
fi

# ═══════════════════════════════════════════
header "3. COMMANDS"
# ═══════════════════════════════════════════

CMD_COUNT=0
for f in "$ROOT/commands"/*.md; do
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
if [ -f "$ROOT/extension.yml" ]; then
  EXT_CMDS=$(grep -c "file: \"commands/" "$ROOT/extension.yml" 2>/dev/null || echo "0")
  if [ "$EXT_CMDS" -eq "$CMD_COUNT" ]; then
    green "extension.yml registers all $CMD_COUNT commands"
  else
    yellow "extension.yml registers $EXT_CMDS commands but $CMD_COUNT exist"
  fi
fi

# ═══════════════════════════════════════════
header "4. EXTENSION MANIFEST"
# ═══════════════════════════════════════════

if [ -f "$ROOT/extension.yml" ]; then
  green "extension.yml exists"
  if python3 -c "import yaml; yaml.safe_load(open('$ROOT/extension.yml'))" 2>/dev/null; then
    green "extension.yml is valid YAML"
  else
    red "extension.yml has YAML syntax errors"
  fi

  # Check required fields
  for field in "id:" "name:" "version:" "description:" "speckit_version:"; do
    if grep -q "$field" "$ROOT/extension.yml"; then
      green "extension.yml has $field"
    else
      red "extension.yml missing $field"
    fi
  done
else
  red "extension.yml not found"
fi

# ═══════════════════════════════════════════
header "5. CONFIG TEMPLATE"
# ═══════════════════════════════════════════

if [ -f "$ROOT/config-template.yml" ]; then
  green "config-template.yml exists"
  if python3 -c "import yaml; yaml.safe_load(open('$ROOT/config-template.yml'))" 2>/dev/null; then
    green "config-template.yml is valid YAML"
    SECTIONS=$(python3 -c "
import yaml
data = yaml.safe_load(open('$ROOT/config-template.yml'))
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
  if [ -f "$ROOT/knowledge-base/$f" ]; then
    if python3 -c "import yaml; yaml.safe_load(open('$ROOT/knowledge-base/$f'))" 2>/dev/null; then
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
  if [ -f "$ROOT/templates/$f" ]; then
    green "templates/$f"
  else
    red "templates/$f not found"
  fi
done

# Check state-schema.json is valid JSON
if [ -f "$ROOT/templates/state-schema.json" ]; then
  if python3 -c "import json; json.load(open('$ROOT/templates/state-schema.json'))" 2>/dev/null; then
    green "state-schema.json is valid JSON"
  else
    red "state-schema.json has JSON syntax errors"
  fi
fi

# ═══════════════════════════════════════════
header "8. SCRIPTS"
# ═══════════════════════════════════════════

for f in detect-project.sh run-understanding.sh setup-worktree.sh migrate-kb.sh; do
  if [ -f "$ROOT/scripts/bash/$f" ]; then
    if [ -x "$ROOT/scripts/bash/$f" ]; then
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
data = yaml.safe_load(open('$ROOT/extension/agents.yaml'))
agent = data.get('agents', {}).get('$agent', {})
print(agent.get('file', 'NOT_FOUND'))
" 2>/dev/null || echo "NOT_FOUND")

  if [ -f "$ROOT/$file" ]; then
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
data = yaml.safe_load(open('$ROOT/extension/agents.yaml'))
agent = data.get('agents', {}).get('$agent', {})
print(agent.get('file', 'NOT_FOUND'))
" 2>/dev/null || echo "NOT_FOUND")

  if [ -f "$ROOT/$file" ]; then
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
data = yaml.safe_load(open('$ROOT/extension/agents.yaml'))
agent = data.get('agents', {}).get('$agent', {})
print(agent.get('file', 'NOT_FOUND'))
" 2>/dev/null || echo "NOT_FOUND")

  if [ -f "$ROOT/$file" ]; then
    green "  Learn: $agent → $file"
  else
    red "  Learn: $agent → $file (FILE NOT FOUND)"
  fi
done

# ═══════════════════════════════════════════
header "10. ROLE SEPARATION VALIDATION"
# ═══════════════════════════════════════════

# Check that WHY agent has NEVER rewrite rules
if grep -q "NEVER rewrite" "$ROOT/agents/exploration/sage.md" 2>/dev/null; then
  green "WHY has NEVER-rewrite rules"
else
  red "WHY is missing NEVER-rewrite rules — ROLE VIOLATION RISK"
fi

# Check that IMPLEMENTER has NEVER modify specs rule
if grep -q "NEVER modify spec" "$ROOT/agents/build/implementer.md" 2>/dev/null; then
  green "IMPLEMENTER has NEVER-modify-specs rule"
else
  red "IMPLEMENTER missing NEVER-modify-specs — ROLE VIOLATION RISK"
fi

# Check that SPEC GUARD has NEVER fix code rule
if grep -q "NEVER fix code" "$ROOT/agents/build/spec-guard.md" 2>/dev/null; then
  green "SPEC GUARD has NEVER-fix-code rule"
else
  red "SPEC GUARD missing NEVER-fix-code — ROLE VIOLATION RISK"
fi

# Check MANAGER has role separation section
if grep -q "Role Separation" "$ROOT/commands/echelon.run.md" 2>/dev/null; then
  green "MANAGER command has Role Separation section"
else
  red "MANAGER command missing Role Separation — agents may cross roles"
fi

# ═══════════════════════════════════════════
header "11. ENFORCEMENT INFRASTRUCTURE"
# ═══════════════════════════════════════════

if [ -f "$ROOT/scripts/bash/pre-dispatch-gate.sh" ]; then
  if [ -x "$ROOT/scripts/bash/pre-dispatch-gate.sh" ]; then
    green "pre-dispatch-gate.sh exists and is executable"
  else
    yellow "pre-dispatch-gate.sh exists but not executable"
  fi
else
  yellow "pre-dispatch-gate.sh not found — enforcement not available"
fi

if [ -f "$ROOT/scripts/bash/post-execution-audit.sh" ]; then
  if [ -x "$ROOT/scripts/bash/post-execution-audit.sh" ]; then
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
