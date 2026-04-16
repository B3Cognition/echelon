#!/usr/bin/env bash
# integration-smoke-test.sh — Full install + deploy smoke test for echelon + extensions
#
# What it does:
#   1. Creates a temp workspace (or uses --dir if provided)
#   2. Inits speckit in that workspace
#   3. Installs echelon (dev) + optional extensions (understanding, revenge, gauntlet)
#   4. Validates what got deployed to .claude/agents/ and .claude/skills/
#   5. Runs echelon dry-run validation against the installed extension
#   6. Reports pass/fail summary
#
# Usage:
#   ./scripts/bash/integration-smoke-test.sh [options]
#
# Options:
#   --dir PATH         Use existing directory instead of creating a temp one
#   --keep             Keep the temp directory after the run (for inspection)
#   --gauntlet PATH    Path to local gauntlet repo (skip if not provided)
#   --understanding    Install understanding extension (requires understanding CLI in PATH)
#   --revenge PATH     Path to local revenge repo
#   --ai AGENT         AI assistant to init for (default: claude)
#   --verbose          Show full output of each step
#
# Example:
#   ./scripts/bash/integration-smoke-test.sh \
#     --gauntlet /Users/michalbachorik/work/evolution/gauntlet \
#     --keep --verbose

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ECHELON_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── defaults ──────────────────────────────────────────────────────────────────
WORK_DIR=""
KEEP=false
GAUNTLET_PATH=""
REVENGE_PATH=""
AI_AGENT="claude"
VERBOSE=false
INSTALL_UNDERSTANDING=false

# ── parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)       WORK_DIR="$2"; shift 2 ;;
    --keep)      KEEP=true; shift ;;
    --gauntlet)  GAUNTLET_PATH="$2"; shift 2 ;;
    --understanding) INSTALL_UNDERSTANDING=true; shift ;;
    --revenge)   REVENGE_PATH="$2"; shift 2 ;;
    --ai)        AI_AGENT="$2"; shift 2 ;;
    --verbose)   VERBOSE=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── colour helpers ─────────────────────────────────────────────────────────────
PASS=0; FAIL=0; WARN=0; SKIP=0
green()  { printf "\033[32m  ✓\033[0m %s\n" "$1"; PASS=$((PASS+1)); }
red()    { printf "\033[31m  ✗\033[0m %s\n" "$1"; FAIL=$((FAIL+1)); }
yellow() { printf "\033[33m  ⚠\033[0m %s\n" "$1"; WARN=$((WARN+1)); }
skip()   { printf "\033[90m  –\033[0m %s\n" "$1"; SKIP=$((SKIP+1)); }
header() { printf "\n\033[1;36m══ %s ══\033[0m\n\n" "$1"; }
info()   { printf "    \033[90m%s\033[0m\n" "$1"; }

run_step() {
  local label="$1"; shift
  if "$VERBOSE"; then
    "$@" && green "$label" || { red "$label"; return 1; }
  else
    local out
    if out=$("$@" 2>&1); then
      green "$label"
    else
      red "$label"
      echo "$out" | tail -5 | sed 's/^/      /'
      return 1
    fi
  fi
}

# ── locate specify CLI ────────────────────────────────────────────────────────
SPECIFY_CMD=""
for candidate in \
  "$ECHELON_ROOT/../../spec-kit-skills-agents/.venv312/bin/specify" \
  "$(dirname "$(dirname "$ECHELON_ROOT")")/spec-kit-skills-agents/.venv312/bin/specify" \
  "specify"; do
  if [[ -x "$candidate" ]] || command -v "$candidate" &>/dev/null 2>&1; then
    SPECIFY_CMD="$candidate"
    break
  fi
done

# ── setup workspace ────────────────────────────────────────────────────────────
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║     ECHELON — INTEGRATION SMOKE TEST                  ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "  Echelon root : $ECHELON_ROOT"
echo "  AI agent     : $AI_AGENT"

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d)"
  echo "  Workspace    : $WORK_DIR  (temp — use --keep to retain)"
  CLEANUP_ON_EXIT=true
else
  echo "  Workspace    : $WORK_DIR  (provided)"
  CLEANUP_ON_EXIT=false
fi

if [[ "$KEEP" == true ]]; then
  CLEANUP_ON_EXIT=false
fi

cleanup() {
  if [[ "$CLEANUP_ON_EXIT" == true && -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

# ─────────────────────────────────────────────────────────────────────────────
header "1. PREREQUISITES"
# ─────────────────────────────────────────────────────────────────────────────

if [[ -n "$SPECIFY_CMD" ]]; then
  VER=$("$SPECIFY_CMD" --version 2>/dev/null | head -1 || echo "unknown")
  green "specify CLI found: $SPECIFY_CMD ($VER)"
else
  red "specify CLI not found — set virtualenv active or check PATH"
  echo ""
  echo "  Hint: source /path/to/spec-kit-skills-agents/.venv312/bin/activate"
  exit 1
fi

if [[ -f "$ECHELON_ROOT/extension.yml" ]]; then
  ECHELON_VER=$(grep "^  version:" "$ECHELON_ROOT/extension.yml" | head -1 | awk '{print $2}' | tr -d '"')
  green "Echelon found at $ECHELON_ROOT (v$ECHELON_VER)"
else
  red "Echelon extension.yml not found at $ECHELON_ROOT"
  exit 1
fi

if [[ -n "$GAUNTLET_PATH" ]]; then
  if [[ -f "$GAUNTLET_PATH/extension.yml" ]]; then
    GAUNTLET_VER=$(grep "^  version:" "$GAUNTLET_PATH/extension.yml" | head -1 | awk '{print $2}' | tr -d '"')
    green "Gauntlet found at $GAUNTLET_PATH (v$GAUNTLET_VER)"
  else
    red "Gauntlet extension.yml not found at $GAUNTLET_PATH"
    GAUNTLET_PATH=""
  fi
else
  skip "Gauntlet path not provided (--gauntlet PATH to include)"
fi

if [[ -n "$REVENGE_PATH" ]]; then
  if [[ -f "$REVENGE_PATH/extension.yml" ]]; then
    green "Revenge found at $REVENGE_PATH"
  else
    red "Revenge extension.yml not found at $REVENGE_PATH"
    REVENGE_PATH=""
  fi
else
  skip "Revenge path not provided (--revenge PATH to include)"
fi

if [[ "$INSTALL_UNDERSTANDING" == true ]]; then
  if command -v understanding &>/dev/null 2>&1; then
    green "understanding CLI available"
  else
    yellow "understanding CLI not found in PATH — skipping understanding install"
    INSTALL_UNDERSTANDING=false
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
header "2. WORKSPACE INIT"
# ─────────────────────────────────────────────────────────────────────────────

cd "$WORK_DIR"

# Init git repo (specify requires it)
run_step "git init" git init -q .

# Init speckit (--force skips non-empty-dir confirmation, --no-git since we already inited)
run_step "specify init --ai $AI_AGENT" \
  "$SPECIFY_CMD" init . --ai "$AI_AGENT" --no-git --force

info "Workspace structure:"
if "$VERBOSE"; then
  ls -la .specify/ 2>/dev/null || true
fi

# ─────────────────────────────────────────────────────────────────────────────
header "3. EXTENSION INSTALL"
# ─────────────────────────────────────────────────────────────────────────────

# Always install echelon first (gauntlet depends on it)
run_step "specify extension add --dev echelon (v$ECHELON_VER)" \
  "$SPECIFY_CMD" extension add --dev "$ECHELON_ROOT"

if [[ -n "$REVENGE_PATH" ]]; then
  run_step "specify extension add --dev revenge" \
    "$SPECIFY_CMD" extension add --dev "$REVENGE_PATH"
fi

if [[ -n "$GAUNTLET_PATH" ]]; then
  run_step "specify extension add --dev gauntlet (v$GAUNTLET_VER)" \
    "$SPECIFY_CMD" extension add --dev "$GAUNTLET_PATH"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "4. DEPLOY VALIDATION"
# ─────────────────────────────────────────────────────────────────────────────

AGENT_DIR=".claude/agents"
SKILL_DIR=".claude/skills"

if [[ -d "$AGENT_DIR" ]]; then
  AGENT_COUNT=$(find "$AGENT_DIR" -maxdepth 1 -name "*.md" | wc -l | tr -d ' ')
  green "Agent directory exists ($AGENT_COUNT agents deployed)"
  if "$VERBOSE"; then
    find "$AGENT_DIR" -maxdepth 1 -name "*.md" -exec basename {} \; | sort | sed 's/^/    /'
  fi
else
  red "Agent directory .claude/agents/ not created"
fi

if [[ -d "$SKILL_DIR" ]]; then
  # Skills are directories containing SKILL.md (not flat .md files)
  SKILL_COUNT=$(find "$SKILL_DIR" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')
  green "Skill directory exists ($SKILL_COUNT skills deployed)"
  if "$VERBOSE"; then
    find "$SKILL_DIR" -maxdepth 1 -mindepth 1 -type d -exec basename {} \; | sort | sed 's/^/    /'
  fi
else
  yellow ".claude/skills/ not created (skills deployed as agents — check extension.yml)"
fi

# Check key echelon skills deployed (skills are dirs with SKILL.md inside)
KEY_SKILLS=(
  "b3c-echelon-run"
  "b3c-echelon-build"
  "b3c-echelon-status"
)
for skill in "${KEY_SKILLS[@]}"; do
  if [[ -f "$SKILL_DIR/${skill}/SKILL.md" ]]; then
    green "$skill — skill deployed"
  else
    yellow "$skill — not found in .claude/skills/ (may be deployed as command differently)"
  fi
done

# Check key echelon agents are present
KEY_AGENTS=(
  "b3c-echelon-commander"
  "b3c-echelon-scout"
  "b3c-echelon-sage"
  "b3c-echelon-cartographer"
  "b3c-echelon-gatekeeper"
  "b3c-echelon-architect"
  "b3c-echelon-implementer"
)

for agent in "${KEY_AGENTS[@]}"; do
  if [[ -f "$AGENT_DIR/${agent}.md" ]]; then
    # Check color is in frontmatter (behavior deployment sanity check)
    if grep -q "^color:" "$AGENT_DIR/${agent}.md" 2>/dev/null || true; then
      if grep -q "^color:" "$AGENT_DIR/${agent}.md" 2>/dev/null; then
        green "$agent — deployed (color present)"
      else
        yellow "$agent — deployed but missing color frontmatter"
      fi
    fi
  else
    red "$agent — NOT deployed"
  fi
done

# Check PROSPECTOR is NOT deployed (was removed)
if [[ -f "$AGENT_DIR/b3c-echelon-prospector.md" ]]; then
  red "b3c-echelon-prospector.md still deployed — should have been removed"
else
  green "PROSPECTOR correctly absent from deployed agents"
fi

# Check extension registry (.specify/extensions/.registry)
if [[ -f ".specify/extensions/.registry" ]]; then
  REGISTERED=$(python3 -c "import json,sys; d=json.load(open('.specify/extensions/.registry')); print(len(d.get('extensions',{})))" 2>/dev/null || echo "?")
  green "Extension registry exists ($REGISTERED extension(s) registered)"
  if "$VERBOSE"; then
    python3 -c "import json; d=json.load(open('.specify/extensions/.registry')); [print('    -',k,'v'+v['version']) for k,v in d.get('extensions',{}).items()]" 2>/dev/null || true
  fi
else
  red "Extension registry not created (.specify/extensions/.registry)"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "5. ECHELON DRY-RUN"
# ─────────────────────────────────────────────────────────────────────────────

INSTALLED_ECHELON=".specify/extensions/echelon"

if [[ -d "$INSTALLED_ECHELON" ]]; then
  # Run dry-run; knowledge-base files are absent on fresh install (expected) — captured as warnings not failures
  DRY_RUN_OUT=$(bash "$ECHELON_ROOT/scripts/bash/dry-run.sh" "$INSTALLED_ECHELON" 2>&1) || true
  # Extract total FAIL count from the summary line, e.g. "✗ FAIL: 5"
  DRY_FAIL=$(echo "$DRY_RUN_OUT" | grep -o 'FAIL: [0-9]*' | awk -F': ' '{print $2}' | head -1)
  DRY_FAIL=${DRY_FAIL:-0}
  DRY_KB_FAIL=$(echo "$DRY_RUN_OUT" | grep -c "knowledge-base.*not found" 2>/dev/null || echo "0")
  DRY_REAL_FAIL=$(( DRY_FAIL - DRY_KB_FAIL ))

  if [[ "$DRY_REAL_FAIL" -eq 0 ]]; then
    green "Echelon dry-run — structural validation passed"
    if [[ "$DRY_KB_FAIL" -gt 0 ]]; then
      yellow "  knowledge-base files absent ($DRY_KB_FAIL) — expected on fresh install, created on first run"
    fi
  else
    red "Echelon dry-run — $DRY_REAL_FAIL structural failure(s) (excluding knowledge-base)"
    echo "$DRY_RUN_OUT" | grep "✗" | grep -v "knowledge-base" | head -10 | sed 's/^/      /'
  fi
  if "$VERBOSE"; then
    echo "$DRY_RUN_OUT" | tail -10 | sed 's/^/    /'
  fi
else
  red "Echelon not found at $INSTALLED_ECHELON — install step may have failed"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "SUMMARY"
# ─────────────────────────────────────────────────────────────────────────────

echo "  ✓ PASS : $PASS"
echo "  ✗ FAIL : $FAIL"
echo "  ⚠ WARN : $WARN"
echo "  – SKIP : $SKIP"
echo ""

if [[ "$KEEP" == true || "$CLEANUP_ON_EXIT" == false ]]; then
  echo "  Workspace retained at: $WORK_DIR"
  echo ""
fi

if [[ $FAIL -gt 0 ]]; then
  echo "  Result: FAIL ($FAIL failures)"
  exit 1
else
  echo "  Result: PASS"
  exit 0
fi
