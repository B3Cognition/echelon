# Phase: codegen-0-preflight
# Source: echelon.codegen.md §Phase 0 — Pre-Flight Checks
# Read by: echelon-orchestrator (ORCHESTRATOR) before Phase 1 RE

**Execution Continuity:** After each Bash tool call, immediately execute the next step without pausing unless a hard stop condition is reached.

### 0.1 Derive WING and spec files

```bash
# WING already set in A.1; spec files are the echelon feature artifacts
SPEC_FILES="${FEATURE_DIR}/spec.md ${FEATURE_DIR}/research.md"
echo "WING=${WING}"
echo "SPEC_FILES=${SPEC_FILES}"
```

### 0.2 Mine spec into MemPalace

```bash
ALREADY_MINED=$(codegen requirements search "." --wing $WING --n 1 2>/dev/null | grep -c "room:" || echo "0")

if [ "$ALREADY_MINED" -eq 0 ]; then
  echo "[CODEGEN RE] No requirements in MemPalace for wing=$WING — mining now..."
else
  echo "[CODEGEN RE] Re-mining updated specs — wing=${WING}..."
fi

for f in "${FEATURE_DIR}/spec.md" "${FEATURE_DIR}/research.md"; do
  [ -f "$f" ] && codegen requirements mine "$f" --wing $WING
done
echo "[CODEGEN RE] MemPalace ready — wing=${WING}"
```

### 0.3 Build environment verification

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

If no test runner binary found: always print a warning and record `tier1_gate: "unavailable"`. Do NOT block pipeline start.

### 0.4 Initialize pipeline state

```bash
PIPELINE_ID=$(uuidgen)
WALL_CLOCK_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

Write initial `codegen-state.json` with pipeline_id, mode (`spec-driven`), intent (from `spec.md` title), wing, `current_phase: "RE"`.

Write the SOAR gate sentinel:
```bash
touch .codegen-active
```

Define `write_state` helper (called after every phase transition):

```bash
write_state() {
  [ -z "${HARNESS_STATE_FILE:-}" ] && return 0
  local phase="$1" phase_status="$2" completed="${3:-0}" current="${4:-null}" verdict="${5:-null}"
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

### 0.5 SOAR bridge initialization

```bash
export CODEGEN_REQUIRE_MODEL_A=1
codegen --verbose gate --phase RE --language python --files /dev/null --state-file codegen-state.json 2>&1 | grep -E "Model A|Model B|soar_model|RuntimeError" | head -5
```

Print: `[CODEGEN] SOAR Model A active`. If `RuntimeError` appears, halt and print install hint.
