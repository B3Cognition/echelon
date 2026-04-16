---
name: speckit.echelon.codegen
description: "SOAR-powered build pipeline for echelon — Phase A validation, MemPalace mining, strategy registration, then RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER"
tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

## User Input

$ARGUMENTS

---

## Architectural Invariants — Read Before Proceeding

These invariants are constitutionally mandated and CANNOT be overridden by any phase, LLM advisory, or commercial pressure:

- **INV-001:** `chunk never` MUST be the first directive in every `.soar` config file. SOAR chunking is disabled in all production deployments.
- **INV-002:** Quality constraints MUST be enforced exclusively via SOAR CQ-ISC prohibit preferences. No LLM advisory output, guardrail, or IMPLEMENTER-level logic may substitute.
- **INV-003:** IMPLEMENTER outputs inject `best` preferences ONLY. IMPLEMENTER does NOT inject prohibit, require, or worst preferences.
- **INV-004:** Every SOAR phase transition MUST produce an EPMEM entry. EPMEM recording cannot be disabled.
- **INV-005:** Every CQ-ISC production rule MUST have `(build ^current-phase <phase>)` as its FIRST LHS condition.
- **INV-006:** SOAR owns the phase transition decision. IMPLEMENTER advises. IMPLEMENTER does NOT self-advance the pipeline.
- **INV-008:** Conflict impasse = correct behaviour, NOT a failure. Impasse triggers human escalation, not autonomous resolution.
- **INV-010:** Delivery is BLOCKED until all Tier 1 (unit) tests pass via Bash tool execution.

---

## Invocation Forms

```
speckit.echelon.codegen 001-feature-name    # run pipeline on echelon feature
speckit.echelon.codegen --resume            # resume interrupted pipeline
```

---

## Phase A: Echelon Preamble

### A.1 Parse arguments

```bash
PROJECT_ROOT=$(pwd)
ARGUMENTS_RAW="$ARGUMENTS"

if [ "$ARGUMENTS_RAW" = "--resume" ]; then
  RESUME_MODE=1
else
  RESUME_MODE=0
  FEATURE_PATH="$ARGUMENTS_RAW"
  SPEC_ID=$(echo "$FEATURE_PATH" | grep -oE '^[0-9]+')
  FEATURE_DIR="${PROJECT_ROOT}/specs/${FEATURE_PATH}"
  WING="${SPEC_ID}"
  echo "SPEC_ID=${SPEC_ID} WING=${WING} FEATURE_DIR=${FEATURE_DIR}"
fi
```

If not resume and `$ARGUMENTS` is empty or `SPEC_ID` is empty, stop:

```
[ECHELON CODEGEN] ERROR: Feature path required.
Usage: speckit.echelon.codegen 001-feature-name
```

### A.2 Validate Phase A artifacts (skip on resume)

```bash
if [ "$RESUME_MODE" -eq 0 ]; then
  MISSING=""
  for f in spec.md tasks.md constitution.md research.md; do
    [ ! -f "${FEATURE_DIR}/${f}" ] && MISSING="${MISSING} ${f}"
  done
  if [ -n "$MISSING" ]; then
    echo "[ECHELON CODEGEN] ERROR: Missing Phase A artifacts:${MISSING}"
    echo "[ECHELON CODEGEN] Run speckit.echelon.run ${FEATURE_PATH} first."
    exit 1
  fi
  echo "[ECHELON CODEGEN] Phase A artifacts verified ✓"
fi
```

### A.3 Verify dependencies (fail fast)

```bash
export CODEGEN_REQUIRE_MODEL_A=1

SOAR_BIN=""
command -v soar &>/dev/null && SOAR_BIN=$(command -v soar)
[ -z "$SOAR_BIN" ] && [ -f ~/.echelon/soar/bin/soar ] && SOAR_BIN=~/.echelon/soar/bin/soar

if [ -z "$SOAR_BIN" ]; then
  echo "[ECHELON CODEGEN] HARD STOP: SOAR binary not found."
  echo "  Install: bash ~/echelon/scripts/install.sh"
  exit 1
fi

if ! command -v codegen &>/dev/null; then
  echo "[ECHELON CODEGEN] HARD STOP: codegen CLI not found."
  echo "  Install: bash ~/echelon/scripts/install.sh"
  exit 1
fi

echo "[ECHELON CODEGEN] Dependencies verified ✓ (soar=${SOAR_BIN})"
```

### A.4 Set harness state file (direct — no env file)

```bash
HARNESS_STATE_FILE="${PROJECT_ROOT}/.specify/squad/state.json"
mkdir -p "$(dirname "$HARNESS_STATE_FILE")"
echo "[ECHELON CODEGEN] Harness state file: ${HARNESS_STATE_FILE}"
```

### A.5 Register harness strategy file (idempotent, skip on resume)

```bash
if [ "$RESUME_MODE" -eq 0 ]; then
  STRATEGY_DIR="${PROJECT_ROOT}/.specify/harness/strategies/${FEATURE_PATH}"
  STRATEGY_FILE="${STRATEGY_DIR}/codegen.md"
  mkdir -p "$STRATEGY_DIR"

  if [ ! -f "$STRATEGY_FILE" ] || ! grep -qF "command: speckit.echelon.codegen" "$STRATEGY_FILE"; then
    cat > "$STRATEGY_FILE" << EOF
---
command: speckit.echelon.codegen
---
# Codegen Strategy

SOAR-powered build pipeline for ${FEATURE_PATH}.

To run in parallel with the default squad strategy:
  run spec ${FEATURE_PATH} strategies=default,codegen kill_losers
EOF
    echo "[ECHELON CODEGEN] Strategy file registered: ${STRATEGY_FILE}"
  else
    echo "[ECHELON CODEGEN] Strategy file already current: ${STRATEGY_FILE}"
  fi
fi
```

If `RESUME_MODE=1`, skip to **Resume Mode** at the end of this document.

---

## Phase 0: Pre-Flight

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

If no test runner binary found: print warning and record `tier1_gate: "unavailable"`. Do NOT block pipeline start.

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
  local phase="$1" status="$2" completed="${3:-0}" current="${4:-null}" verdict="${5:-null}"
  mkdir -p "$(dirname "$HARNESS_STATE_FILE")"
  cat > "$HARNESS_STATE_FILE" << STATEOF
{
  "status": "${status}",
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

---

## Phase 1: RE — Requirements Lookup

**Print:** `[CODEGEN] Phase RE — Starting...`

```bash
codegen run --intent "<intent from spec.md title>" --wing $WING --state-file codegen-state.json
```

Print the retrieved requirements block. These are what IMPLEMENT will be verified against.

**Write state checkpoint:** `current_phase: "DECOMPOSE"`

```bash
write_state "codegen_decompose" "building" 0 null null
```

**Print:** `[CODEGEN] Phase RE — COMPLETE ✓`

---

## Phase 2: DECOMPOSE — Task Decomposition

**Print:** `[CODEGEN] Phase DECOMPOSE — Starting...`

```
Agent: Decompose the intent into implementation tasks.

Intent: <intent>

Retrieved requirements from MemPalace (RE phase):
<re_phase context from codegen-state.json>

Each task must:
  - Have a unique task-id (T-NNN)
  - Specify: description, scope (module/component), language, estimated complexity
  - Reference the specific FR-*/NFR-*/AC-* IDs from the retrieved requirements that gate it
  - Map to one or more CQ-ISC entries from the library

Output: ./codegen-staging/task-queue.json
```

Inject task WMEs into SOAR. Update state.json: `task_queue.pending = [all task IDs]`, `psi.denominator = |I_D|`.

**Write state checkpoint:** `current_phase: "IMPLEMENT"`

```bash
TOTAL_TASKS=$(jq '.task_queue.pending | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_implement" "building" 0 null null
```

**Print:** `[CODEGEN] Phase DECOMPOSE — COMPLETE ✓ (<N> tasks queued)`

---

## Phase 3: IMPLEMENT — IMPLEMENTER Dispatch Loop

**Print:** `[CODEGEN] Phase IMPLEMENT — Starting (<N> tasks)...`

For each task in `task_queue.pending`:

### 3.1 SOAR dispatches task

Inject task WME into SOAR. SOAR selects DISPATCH_IMPLEMENTER operator.
Print: `[CODEGEN] Task <task-id>: DISPATCHING to IMPLEMENTER...`

### 3.2 IMPLEMENTER executes task

```
Agent (IMPLEMENTER role): Implement task <task-id>: <description>
Scope: <scope>, Language: <language>

Requirements this task must satisfy (from MemPalace):
<FR-*/AC-* entries cited by this task>

CQ-ISC advisory (informational — not enforcement): <relevant CQ-ISC rule texts>

IMPORTANT: You are ADVISING SOAR. Output best-preference recommendations only.
Do NOT make final quality gate decisions — SOAR evaluates all gates.
Generate the implementation files. Write tests.
Report: status (DONE/BLOCKED/NEEDS_CONTEXT), files modified, test results.
```

### 3.3 Static analysis

```bash
ruff check --output-format=json <files> 2>/dev/null || true          # Python
npx eslint --format json <files> 2>/dev/null || true                  # TypeScript
golangci-lint run --out-format json <files> 2>/dev/null || true       # Go
```

### 3.4 Gate evaluation

```bash
codegen gate --phase IMPLEMENT --language <language> --files <files> --state-file codegen-state.json
```

- Exit 0 (ADVANCE): task complete → move to `completed`
- Exit 1 (RETRY): re-dispatch IMPLEMENTER with violation details + failed FR citation
- Exit 2 (ESCALATE): write `codegen-impasse.md`, halt, wait for human

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
CURRENT_TASK=$(jq -r '.task_queue.pending[0] // "null"' codegen-state.json 2>/dev/null || echo null)
if [ "$CURRENT_TASK" = "null" ]; then
  write_state "codegen_implement" "building" $COMPLETED null null
else
  write_state "codegen_implement" "building" $COMPLETED "\"${CURRENT_TASK}\"" null
fi
```

On ESCALATE (exit 2):
```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_implement" "escalated" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase IMPLEMENT — COMPLETE ✓ (<done> done, <blocked> blocked)`

---

## Phase 4: GATE — CQ-ISC Verification Pass

**Print:** `[CODEGEN] Phase GATE — Running CQ-ISC verification...`

```bash
codegen gate --phase GATE --language <language> --files <all-generated-files> --state-file codegen-state.json
```

For each violation print: `[CODEGEN GATE] CQ-ISC violation: <id> in <file>:<line> — <rule>`
And: `[CODEGEN GATE] Traced to: <req_id> — <content>`

If Ψ ≥ 0.70 and zero violations: SOAR → ADVANCE to TEST.
If violations remain: SOAR → RETRY or ESCALATE.

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_test" "building" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase GATE — COMPLETE ✓ (<violation_count> violations blocked)`

---

## Phase 5: Conflict Impasse — Human Escalation

Fires when SOAR detects a conflict impasse (INV-008).

Write `./codegen-impasse.md` with conflicting constraints, code location, and resolution options. Print the impasse report. Halt. Wait for human response.

Record in EPMEM: `^source soar ^operator ESCALATE ^resolution pending`.

---

## Phase 6: TEST — Tier 1 Gate

**Print:** `[CODEGEN] Phase TEST — Running Tier 1 gate (unit tests)...`

```bash
pytest --tb=short --json-report --json-report-file=./codegen-staging/test-results.json 2>&1         # Python
npx vitest run --reporter=json --outputFile=./codegen-staging/test-results.json 2>&1                # TypeScript
go test ./... -json 2>&1 | tee ./codegen-staging/test-results.json                                  # Go
mvn test 2>&1 | tee ./codegen-staging/test-results.log                                              # Java
```

Inject `test-result` WMEs into SOAR.

- All pass: `tier1_gate: "pass"` → ADVANCE to DELIVER
- Any fail: RETRY (back to IMPLEMENT) or ESCALATE

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_deliver" "building" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase TEST — COMPLETE ✓ (Tier 1 gate PASSED)`

---

## Phase 7: DELIVER

**Print:** `[CODEGEN] Phase DELIVER — Assembling delivery package...`

SOAR selects DELIVER only when: all Tier 1 tests pass, Ψ ≥ 0.70, zero CQ-ISC violations.

1. Write `./codegen-report.md` — human-readable summary with requirement citations per delivered feature.
2. Export EPMEM:
   ```bash
   codegen gate --phase DELIVER --language <language> --files <files> --state-file codegen-state.json
   ```
3. Update `codegen-state.json`: `wall_clock_end = now`.

**Git operations:** Present for user approval — do NOT execute without it:
```
[CODEGEN] Proposed git operations:
  git add <generated files>
  git commit -m "codegen: <intent summary>"
Approve? (yes/no):
```

```bash
rm -f .codegen-active
write_state "done" "build_done" $TOTAL_TASKS null '"PASS"'
```

---

## Terminal Summary

```
╔══════════════════════════════════════════════════════╗
║         CODEGEN — Pipeline Summary                   ║
╠══════════════════════════════════════════════════════╣
║ Pipeline ID : <pipeline_id>                          ║
║ Wing        : <wing>                                 ║
║ Feature     : <feature_path>                         ║
║ Final phase : <DELIVER|BLOCKED|ESCALATED>            ║
╠══════════════════════════════════════════════════════╣
║ Requirements: <N> retrieved from MemPalace           ║
║ Ψ score     : <score> (threshold 0.70)               ║
║ Tier 1 gate : <PASS|FAIL|UNAVAILABLE>                ║
║ CQ-ISC violations blocked : <count>                  ║
║ Impasse escalations       : <count>                  ║
║ Wall-clock time           : <HH:MM:SS>               ║
╠══════════════════════════════════════════════════════╣
║ Tasks: <done> done / <blocked> blocked / <total> total║
╚══════════════════════════════════════════════════════╝
```

---

## Resume Mode

If `$ARGUMENTS` is `--resume`:

```bash
if [ ! -f codegen-state.json ]; then
  echo "[ECHELON CODEGEN] ERROR: No codegen-state.json found. Cannot resume."
  exit 1
fi

RESUME_PHASE=$(jq -r '.current_phase' codegen-state.json | tr '[:upper:]' '[:lower:]')
RESUME_COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
TOTAL_TASKS=$(jq '(.task_queue.pending | length) + (.task_queue.completed | length)' codegen-state.json 2>/dev/null || echo 0)
WING=$(jq -r '.wing' codegen-state.json 2>/dev/null || echo "unknown")

write_state() {
  local phase="$1" status="$2" completed="${3:-0}" current="${4:-null}" verdict="${5:-null}"
  mkdir -p "$(dirname "$HARNESS_STATE_FILE")"
  cat > "$HARNESS_STATE_FILE" << STATEOF
{
  "status": "${status}", "phase": "${phase}",
  "build": { "total_tasks": ${TOTAL_TASKS:-0}, "completed_tasks": ${completed}, "current_task": ${current}, "verification_verdict": ${verdict} },
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
STATEOF
}
write_state "codegen_${RESUME_PHASE}" "building" $RESUME_COMPLETED null null
```

Display:
```
[CODEGEN RESUME]
Pipeline ID : <pipeline_id>
Wing        : <wing>
Resuming at : <current_phase>
Completed   : <phases_completed joined by " → ">
Tasks done  : <completed> / <total>
Ψ score     : <psi.score> (threshold 0.70)
Tier 1 gate : <tier1_gate>
```

Jump to `current_phase`. Do NOT re-mine specs — MemPalace already has them.

---

## Error Handling

| Error | Response |
|-------|----------|
| Missing Phase A artifact | STOP — print which file is missing + hint to run `speckit.echelon.run` |
| SOAR binary not found | HARD STOP — print `bash ~/echelon/scripts/install.sh` |
| codegen CLI not found | HARD STOP — print `bash ~/echelon/scripts/install.sh` |
| No test runner found | Warn, mark tier1 unavailable, generate CI config |
| Impasse (exit 2) | Stop, report `codegen-impasse.md` — do NOT enter feedback loop |
| Context window limit | Write state.json, print `[CODEGEN] Run speckit.echelon.codegen --resume to continue` |
| Filesystem write outside target | BLOCK — `[CODEGEN SECURITY] Write outside target blocked` |
