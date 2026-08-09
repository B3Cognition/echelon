# Phase: codegenlight-0-preflight
# Source: echelon.codegenlight.md §Phase 0 — Pre-Flight Checks
# Read by: echelon.orchestrator (ORCHESTRATOR) before Phase 1 RE

Before entering any pipeline phase, run ALL of these checks via Bash tool.

### 0.1 — Parse arguments and derive WING

```bash
WING=$(python3 -c "
import sys, yaml
try:
    c = yaml.safe_load(open('.echelon/config.yml'))
    w = (c or {}).get('mempalace', {}).get('wing', '')
    if not w:
        print('ERROR: wing not set in .echelon/config.yml — run: echelon workspace init', file=sys.stderr)
        sys.exit(1)
    print(w)
except FileNotFoundError:
    print('ERROR: .echelon/config.yml not found — run: echelon workspace init', file=sys.stderr)
    sys.exit(1)
" 2>&1) || exit 1
if echo "$WING" | grep -q "^ERROR:"; then
    echo "$WING" >&2
    exit 1
fi
echo "WING=${WING}"
```

The wing is the project identity in MemPalace. All requirements, decisions, and patterns for this project are stored under this name. Always keep it stable for the same project directory; it never changes.

### 0.2 — Spec detection and mining

**This step is mandatory whenever spec files are provided or found.**

```bash
# Check if spec glob was passed as argument (e.g. specs/*.md, docs/*.md)
SPEC_GLOB="<first token if spec-driven mode, else empty>"

# If explicit spec glob provided — expand it
if [ -n "$SPEC_GLOB" ]; then
  SPEC_FILES=$(ls $SPEC_GLOB 2>/dev/null)
  if [ -n "$SPEC_FILES" ]; then
    echo "[CODEGEN] Spec files found: $(echo $SPEC_FILES | wc -w | tr -d ' ') files"
    echo "$SPEC_FILES"
  else
    echo "[CODEGEN WARNING] Spec glob '$SPEC_GLOB' matched no files"
    SPEC_GLOB=""
  fi
fi

# If no explicit glob — auto-discover spec files in common locations
if [ -z "$SPEC_GLOB" ]; then
  AUTO_SPECS=$(ls specs/*.md docs/*.md *.md 2>/dev/null | grep -v README | grep -v CHANGELOG | head -20)
  if [ -n "$AUTO_SPECS" ]; then
    echo "[CODEGEN] Auto-discovered spec files:"
    echo "$AUTO_SPECS"
    SPEC_GLOB="auto"
    SPEC_FILES="$AUTO_SPECS"
  fi
fi
```

**If spec files found — mine them into MemPalace:**

```bash
# Check if requirements already mined for this wing
ALREADY_MINED=$(codegen requirements search "." --wing $WING --n 1 2>/dev/null | grep -c "room:" || echo "0")

if [ "$ALREADY_MINED" -eq 0 ]; then
  echo "[CODEGEN RE] No requirements in MemPalace for wing=$WING — mining now..."
  if [ -n "$SPEC_FILES" ]; then
    # Mine each spec file individually
    for f in $SPEC_FILES; do
      echo "[CODEGEN RE] Mining: $f"
      codegen requirements mine "$f" --wing $WING
    done
  fi
else
  echo "[CODEGEN RE] Requirements already in MemPalace for wing=$WING ($ALREADY_MINED drawers found)"
  echo "[CODEGEN RE] Re-mining updated specs..."
  if [ -n "$SPEC_FILES" ]; then
    for f in $SPEC_FILES; do
      codegen requirements mine "$f" --wing $WING
    done
  fi
fi
```

Print mining summary:
```
[CODEGEN RE] Requirements ready in MemPalace — wing=<WING>
[CODEGEN RE] Run `codegen requirements search "<topic>" --wing <WING>` to inspect
```

### 0.3 — Build environment verification (FR-CMD-005)

Run via Bash tool:
```bash
STACK_DETECTED=""
TEST_RUNNER_BIN=""

if [ -f "pyproject.toml" ] || [ -f "setup.py" ] || [ -f "requirements.txt" ]; then
  STACK_DETECTED="python"
  TEST_RUNNER_BIN=$(which pytest 2>/dev/null)
fi
if [ -f "package.json" ] || [ -f "tsconfig.json" ]; then
  STACK_DETECTED="${STACK_DETECTED}:typescript"
  TEST_RUNNER_BIN=$(which vitest 2>/dev/null || which jest 2>/dev/null || which npx 2>/dev/null)
fi
if [ -f "go.mod" ] || [ -f "go.sum" ]; then
  STACK_DETECTED="${STACK_DETECTED}:go"
  TEST_RUNNER_BIN=$(which go 2>/dev/null)
fi
if [ -f "pom.xml" ] || [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
  STACK_DETECTED="${STACK_DETECTED}:java"
  TEST_RUNNER_BIN=$(which mvn 2>/dev/null || which gradle 2>/dev/null)
fi

echo "STACK=${STACK_DETECTED}"
echo "TEST_RUNNER=${TEST_RUNNER_BIN}"
```

If no test runner binary found, always print a warning and record `tier1_gate: "unavailable"`. DO NOT block pipeline start.

### 0.4 — Initialize pipeline state

```bash
PIPELINE_ID=$(uuidgen)
WALL_CLOCK_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

Write initial `codegen-state.json` with pipeline_id, mode, intent, wing, `current_phase: "RE"`.

Write the SOAR gate sentinel:
```bash
touch .codegen-active
```

### 0.4.1 — Initialize harness-compatible state

Define the `write_state` helper (call after every phase transition).

When running inside echelon-harness, `echelon.codegen` sets `HARNESS_STATE_FILE` by
writing `.codegen-harness-env` before delegating here. When running standalone
(`/codegen` without echelon), no `.codegen-harness-env` is present and `write_state`
is a no-op — always leave harness state untouched; the harness state file is never written.

```bash
# Load harness integration env written by echelon.codegen wrapper (if present)
[ -f .codegen-harness-env ] && source .codegen-harness-env

write_state() {
  # no-op when not running inside echelon-harness
  [ -z "${HARNESS_STATE_FILE:-}" ] && return 0
  local phase="$1"          # e.g. "codegen_re"
  local phase_status="$2"   # building | build_done | blocked | escalated
  local completed="${3:-0}"
  local current="${4:-null}"
  local verdict="${5:-null}"
  mkdir -p "$(dirname "$HARNESS_STATE_FILE")"
  cat > "$HARNESS_STATE_FILE" << STATEOF
{
  "status": "${phase_status}",
  "phase": "${phase}",
  "build": {
    "total_tasks": ${TOTAL_TASKS:-0},
    "completed_tasks": ${completed},
    "current_task": ${current},
    "verification_verdict": ${verdict}
  },
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
STATEOF
}

TOTAL_TASKS=0
write_state "codegen_re" "building" 0 null null
```

### 0.5 — SOAR bridge initialization

Export `CODEGEN_REQUIRE_MODEL_A=1` so the bridge hard-fails if Model A cannot
start, rather than silently drifting onto the slower per-phase fallback.

```bash
export CODEGEN_REQUIRE_MODEL_A=1
codegen --verbose gate --phase RE --language python --files /dev/null --state-file codegen-state.json 2>&1 | grep -E "Model A|Model B|soar_model|RuntimeError" | head -5
```

Print: `[CODEGEN] SOAR Model A active`. If a `RuntimeError` surfaces from the
bridge, halt and surface the install hint — Model B is not acceptable under
this enforcement.
