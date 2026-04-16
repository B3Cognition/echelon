---
name: speckit.echelon.codegenlight
description: SOAR-powered software development agent — brownfield RE + greenfield build with inviolable quality gates (CQ-ISC prohibit preferences via SOAR 9.6.4)
tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

# /codegen — SOAR-Powered Software Development Agent

## User Input

$ARGUMENTS

---

## Architectural Invariants — Read Before Proceeding

These invariants are constitutionally mandated and CANNOT be overridden by any phase, LLM advisory, or commercial pressure:

- **INV-001:** `chunk never` MUST be the first directive in every `.soar` config file. SOAR chunking is disabled in all production deployments. ISS-007 (Second-Order Chunking Contamination) is Grade A CONFIRMED SEVERE.
- **INV-002:** Quality constraints MUST be enforced exclusively via SOAR CQ-ISC prohibit preferences. No LLM advisory output, guardrail, or IMPLEMENTER-level logic may substitute for prohibit preferences.
- **INV-003:** IMPLEMENTER outputs inject `best` preferences ONLY. IMPLEMENTER does NOT inject prohibit, require, or worst preferences.
- **INV-004:** Every SOAR phase transition MUST produce an EPMEM entry. EPMEM recording cannot be disabled.
- **INV-005:** Every CQ-ISC production rule MUST have `(build ^current-phase <phase>)` as its FIRST LHS condition.
- **INV-006:** SOAR owns the phase transition decision. IMPLEMENTER advises. IMPLEMENTER does NOT self-advance the pipeline.
- **INV-008:** Conflict impasse = correct behaviour, NOT a failure. Impasse triggers human escalation, not autonomous resolution.
- **INV-010:** Delivery is BLOCKED until all Tier 1 (unit) tests pass via Bash tool execution.

---

## Invocation Forms

Parse `$ARGUMENTS` to determine mode:

```
/codegen <spec-glob> <intent>      # spec-driven: mine specs → RE lookup → build
/codegen <target-path> <intent>    # brownfield: RE existing codebase, then build
/codegen <intent>                  # greenfield: domain research, then build
/codegen --resume                  # resume interrupted pipeline from state.json
/codegen --benchmark               # run E2E benchmark vs LLM-only baseline
```

**Parsing rules (in order):**
1. If `$ARGUMENTS` starts with `--resume`: enter RESUME mode.
2. If `$ARGUMENTS` starts with `--benchmark`: enter BENCHMARK mode.
3. If the first token contains `*` or ends with `.md` or `.yaml` or `.yml` and matches files on disk (test with `ls <token> 2>/dev/null`): **spec-driven mode** — first token(s) = spec glob, remainder = intent.
4. If the first token is a filesystem path (test with `test -e <token>`): brownfield mode; first token = target-path, remainder = intent.
5. Otherwise: greenfield mode; entire `$ARGUMENTS` = intent.

---

## Phase 0: Pre-Flight Checks

Before entering any pipeline phase, run ALL of these checks via Bash tool.

### 0.1 — Parse arguments and derive WING

```bash
# Derive project wing from current directory name
WING=$(basename $(pwd))
echo "WING=${WING}"
```

The wing is the project identity in MemPalace. All requirements, decisions, and patterns for this project are stored under this name. It never changes for the same project directory.

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

If no test runner binary found, print warning and record `tier1_gate: "unavailable"`. DO NOT block pipeline start.

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
is a no-op — the harness state file is never written.

```bash
# Load harness integration env written by echelon.codegen wrapper (if present)
[ -f .codegen-harness-env ] && source .codegen-harness-env

write_state() {
  # no-op when not running inside echelon-harness
  [ -z "${HARNESS_STATE_FILE:-}" ] && return 0
  local phase="$1"   # e.g. "codegen_re"
  local status="$2"  # building | build_done | blocked | escalated
  local completed="${3:-0}"
  local current="${4:-null}"
  local verdict="${5:-null}"
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

---

## Phase 1: RE — Requirements Lookup + Domain Research

**Print:** `[CODEGEN] Phase RE — Starting...`

### Step 1.1 — MemPalace requirements retrieval (always runs first)

```bash
# Retrieve requirements relevant to the intent from MemPalace
codegen run --intent "<intent>" --wing $WING --state-file codegen-state.json
```

This triggers the RE phase hook which:
- Searches MemPalace for requirements relevant to the intent
- Injects a `re-requirements-context` WME into SOAR
- Writes retrieved requirements to `codegen-state.json` under `re_phase`
- Records an EPMEM transition (INV-004)

Print the retrieved requirements block — these are what IMPLEMENT will be verified against.

### Step 1.2 — Additional RE (if brownfield target provided)

If a `<target-path>` was given, additionally delegate to GOLDDIGGER via Agent tool:
```
Agent: Analyze <target_path>.
Produce: glossary.md, mental-model.md, boundaries.md, unknowns.md, assumptions.md in ./codegen-staging/.
Identify stack, test runner, |I_D| estimate with confidence level.
Extract constitution.md if present.
```

If no `<target-path>` and MemPalace returned requirements: **skip domain research** — the spec is the domain model. Go straight to DECOMPOSE.

If no `<target-path>` AND MemPalace returned nothing: treat as greenfield, research the domain:
```
Agent: Intent is: <intent>
Research reference architectures. Produce mental-model.md, boundaries.md in ./codegen-staging/.
Extract acceptance criteria for |I_D| estimate.
```

If still no acceptance criteria: **STOP and ask user** before proceeding.

**Write state checkpoint:** `current_phase: "DECOMPOSE"`

Update harness state:
```bash
write_state "codegen_decompose" "building" 0 null null
```

**Print:** `[CODEGEN] Phase RE — COMPLETE ✓`

---

## Phase 2: DECOMPOSE — Task Decomposition

**Print:** `[CODEGEN] Phase DECOMPOSE — Starting...`

Use Agent tool. Provide the retrieved requirements from MemPalace as primary context:

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

Update harness state and set task total:
```bash
TOTAL_TASKS=$(jq '.task_queue.pending | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_implement" "building" 0 null null
```

**Print:** `[CODEGEN] Phase DECOMPOSE — COMPLETE ✓ (<N> tasks queued)`

---

## Phase 3: IMPLEMENT — IMPLEMENTER Dispatch Loop

**Print:** `[CODEGEN] Phase IMPLEMENT — Starting (<N> tasks)...`

For each task in `task_queue.pending`:

### 3.1 — SOAR dispatches task

Inject task WME into SOAR. SOAR selects DISPATCH_IMPLEMENTER operator.
Print: `[CODEGEN] Task <task-id>: DISPATCHING to IMPLEMENTER...`

### 3.2 — IMPLEMENTER executes task

Delegate to IMPLEMENTER via Agent tool (INV-003: `best` preferences ONLY):

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

### 3.3 — Static analysis

```bash
# Python
ruff check --output-format=json <files> 2>/dev/null || true
# TypeScript
npx eslint --format json <files> 2>/dev/null || true
# Go
golangci-lint run --out-format json <files> 2>/dev/null || true
```

### 3.4 — Gate evaluation

```bash
codegen gate --phase IMPLEMENT --language <language> --files <files> --state-file codegen-state.json
```

- Exit 0 (ADVANCE): task complete → move to `completed`
- Exit 1 (RETRY): re-dispatch IMPLEMENTER with violation details. Include the failed FR citation from `requirement_citations` in the retry prompt.
- Exit 2 (ESCALATE): write `codegen-impasse.md`, halt, wait for human

Update harness state on ADVANCE:
```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
CURRENT_TASK=$(jq -r '.task_queue.pending[0] // "null"' codegen-state.json 2>/dev/null || echo null)
if [ "$CURRENT_TASK" = "null" ]; then
  write_state "codegen_implement" "building" $COMPLETED null null
else
  write_state "codegen_implement" "building" $COMPLETED "\"${CURRENT_TASK}\"" null
fi
```

On ESCALATE (exit 2), before writing `codegen-impasse.md`:
```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_implement" "escalated" $COMPLETED null null
```

**Write state checkpoint** after each task.

**Print:** `[CODEGEN] Phase IMPLEMENT — COMPLETE ✓ (<done> done, <blocked> blocked)`

---

## Phase 4: GATE — CQ-ISC Verification Pass

**Print:** `[CODEGEN] Phase GATE — Running CQ-ISC verification...`

```bash
codegen gate --phase GATE --language <language> --files <all-generated-files> --state-file codegen-state.json
```

For each violation:
- Print: `[CODEGEN GATE] CQ-ISC violation: <cq-isc-id> in <file>:<line> — <rule-text>`
- Print cited requirement: `[CODEGEN GATE] Traced to: <req_id> — <content>`

If Ψ ≥ 0.70 and zero violations: SOAR → ADVANCE to TEST.
If violations remain: SOAR → RETRY or ESCALATE.

**Write state checkpoint:** `current_phase: "TEST"`

Update harness state:
```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_test" "building" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase GATE — COMPLETE ✓ (<violation_count> violations blocked)`

---

## Phase 5: Conflict Impasse — Human Escalation

This phase fires when SOAR detects a conflict impasse (INV-008).

Write `./codegen-impasse.md` with conflicting constraints, code location, and resolution options.

Print the impasse report. Halt. Wait for human response.

Record impasse in EPMEM with `^source soar ^operator ESCALATE ^resolution pending`.

---

## Phase 6: TEST — Tier 1 Gate Execution

**Print:** `[CODEGEN] Phase TEST — Running Tier 1 gate (unit tests)...`

Run tests via Bash tool (INV-010: blocking for delivery):
```bash
# Python
pytest --tb=short --json-report --json-report-file=./codegen-staging/test-results.json 2>&1

# TypeScript
npx vitest run --reporter=json --outputFile=./codegen-staging/test-results.json 2>&1

# Go
go test ./... -json 2>&1 | tee ./codegen-staging/test-results.json

# Java
mvn test 2>&1 | tee ./codegen-staging/test-results.log
```

Inject `test-result` WMEs into SOAR.

If all pass: `tier1_gate: "pass"` → ADVANCE to DELIVER.
If any fail: RETRY (back to IMPLEMENT) or ESCALATE.

**Write state checkpoint:** `current_phase: "DELIVER"`

Update harness state:
```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_deliver" "building" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase TEST — COMPLETE ✓ (Tier 1 gate PASSED)`

---

## Phase 7: DELIVER — Final Delivery Package

**Print:** `[CODEGEN] Phase DELIVER — Assembling delivery package...`

SOAR selects DELIVER only when:
- All Tier 1 tests pass
- Ψ ≥ 0.70
- Zero confirmed CQ-ISC violations

When SOAR selects DELIVER:

1. Write `./codegen-report.md` — human-readable summary including requirement citations per delivered feature.
2. Export EPMEM:
   ```bash
   codegen gate --phase DELIVER --language <language> --files <files> --state-file codegen-state.json
   ```
3. Update `codegen-state.json`: `wall_clock_end = now`.

**Git operations (FR-CMD-006):** Present for user approval:
```
[CODEGEN] Proposed git operations:
  git add <generated files>
  git commit -m "codegen: <intent summary>"
Approve? (yes/no):
```
Wait. Do NOT execute without approval.

**Write state checkpoint:** `current_phase: "DONE"`

Remove gate sentinel:
```bash
rm -f .codegen-active
```

```bash
write_state "done" "build_done" $TOTAL_TASKS null '"PASS"'
```

---

## Terminal Summary (FR-CMD-003)

```
╔══════════════════════════════════════════════════════╗
║         CODEGEN — Pipeline Summary                   ║
╠══════════════════════════════════════════════════════╣
║ Pipeline ID : <pipeline_id>                          ║
║ Wing        : <wing>                                 ║
║ Mode        : <brownfield|greenfield|spec-driven>    ║
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

## RESUME Mode

If `--resume`:

1. Read `./codegen-state.json`
2. Display:
   ```
   [CODEGEN RESUME]
   Pipeline ID : <pipeline_id>
   Wing        : <wing>
   Resuming at : <current_phase>
   Completed   : <phases_completed joined by " → ">
   Requirements: <re_phase.requirements_retrieved>
   Tasks done  : <completed> / <total>
   Ψ score     : <psi.score> (threshold <psi.threshold>)
   Tier 1 gate : <tier1_gate>
   ```

3. Restore harness state from `codegen-state.json`:

```bash
RESUME_PHASE=$(jq -r '.current_phase' codegen-state.json | tr '[:upper:]' '[:lower:]')
RESUME_COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
TOTAL_TASKS=$(jq '(.task_queue.pending | length) + (.task_queue.completed | length)' codegen-state.json 2>/dev/null || echo 0)

# Restore harness integration env (written by echelon.codegen on first run)
[ -f .codegen-harness-env ] && source .codegen-harness-env
write_state() {
  [ -z "${HARNESS_STATE_FILE:-}" ] && return 0
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
echo "[CODEGEN RESUME] state.json restored — phase=codegen_${RESUME_PHASE}"
```

4. Jump to `current_phase`. Do NOT re-mine specs on resume — MemPalace already has them.

---

## Error Handling

| Error | Response |
|-------|----------|
| SOAR bridge fails to start | Fall back to Model B, log warning, continue |
| Spec glob matches no files | Warn, continue without requirement mining |
| MemPalace unavailable | Warn, continue without RE lookup — pipeline still runs |
| No test runner found | Warn, mark tier1 unavailable, generate CI config |
| Context window approaching limit | Write state.json, print `[CODEGEN] Context limit — checkpoint written. Run /codegen --resume to continue.` |
| Git auth failure | Log error, skip git, deliver files as-is |
| Filesystem write outside target | BLOCK — `[CODEGEN SECURITY] Write outside target blocked (FR-CMD-006)` |

---

## SOAR Integration Points

```bash
# Gate a phase
codegen gate --phase <PHASE> --language <lang> --files <files> --state-file codegen-state.json

# Check pipeline state
codegen status --state-file codegen-state.json

# Search mined requirements
codegen requirements search "<query>" --wing <wing>

# Mine additional specs mid-run
codegen requirements mine <file> --wing <wing>

# Repair memory if corrupted
codegen memory repair --store epmem
```
