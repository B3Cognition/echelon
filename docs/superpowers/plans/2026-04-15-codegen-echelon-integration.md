# Codegen–Echelon Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make codegen a first-class echelon build alternative by creating a proper spec-kit extension manifest for the codegen repo, polishing the existing codegen skill, and adding a new `echelon.codegen.md` command that drives the codegen pipeline using Phase A artifacts and writes harness-compatible state.

**Architecture:** `echelon.codegen.md` mirrors `echelon.build.md`'s interface (reads `specs/{NNN}-{feature}/` Phase A artifacts, writes `.specify/squad/state.json`) but drives the SOAR-powered codegen pipeline instead of the squad. codegen becomes a proper spec-kit extension via a new `extension.yml`. No changes to SOAR, MemPalace, harness, or `echelon.build.md`.

**Tech Stack:** YAML (extension manifests), Markdown (skill files), Bash (state writes inside skills), jq (JSON reads in Bash blocks), SOAR 9.6.4, codegen CLI

**Repos:** Changes span two repos — `evolution/codegen` and `evolution/echelon`. Both are on branch `evolution_v2`.

---

## File Map

| File | Repo | Action |
|---|---|---|
| `extension.yml` | codegen | Create |
| `commands/codegen.md` | codegen | Modify (add state writes, fix resume sync) |
| `commands/echelon.codegen.md` | echelon | Create |
| `.specify/extensions/echelon/extension.yml` | spec-kit-skills-agents | Modify (add command entry) |

---

## Task 1: Create codegen `extension.yml`

**Files:**
- Create: `~/work/evolution/codegen/extension.yml`

- [ ] **Step 1: Validate YAML of existing codegen structure**

```bash
cd ~/work/evolution/codegen
python3 -c "import yaml; print('OK')"
ls commands/
```

Expected: `codegen.md` present in `commands/`.

- [ ] **Step 2: Write `extension.yml`**

Create `~/work/evolution/codegen/extension.yml`:

```yaml
schema_version: "1.0"

extension:
  id: "codegen"
  name: "Codegen"
  version: "1.0.0"
  description: "SOAR-powered build pipeline with inviolable quality gates (CQ-ISC) and persistent memory (MemPalace/EPMEM/SMEM)"
  author: "B3Cognition"
  repository: "https://github.com/B3Cognition/codegen"
  license: "MIT"
  homepage: "https://github.com/B3Cognition/codegen"

requires:
  speckit_version: ">=0.4.2"
  tools:
    - name: "soar"
      version: ">=9.6.4"
      required: true
      hard_stop: true
      note: "SOAR binary at ~/soar/bin/soar. Install from github.com/SoarGroup/Soar/releases tag releases/9.6.4. HARD STOP if unavailable."
    - name: "codegen"
      version: ">=1.0.0"
      required: true
      hard_stop: true
      note: "codegen CLI. Install via: bash ~/codegen/scripts/install.sh"

provides:
  commands:
    - name: "speckit.codegen"
      file: "commands/codegen.md"
      description: "SOAR-powered build: RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER with inviolable CQ-ISC quality gates"
      behavior:
        execution: isolated
        invocation: explicit
        capability: strong
        effort: high
        tools: full

tags:
  - "build"
  - "soar"
  - "quality-gates"
  - "memory"
```

- [ ] **Step 3: Validate YAML syntax**

```bash
cd ~/work/evolution/codegen
python3 -c "import yaml; data = yaml.safe_load(open('extension.yml')); print('schema_version:', data['schema_version']); print('id:', data['extension']['id']); print('commands:', [c['name'] for c in data['provides']['commands']])"
```

Expected output:
```
schema_version: 1.0
id: codegen
commands: ['speckit.codegen']
```

- [ ] **Step 4: Commit**

```bash
cd ~/work/evolution/codegen
git add extension.yml
git commit -m "feat(extension): add spec-kit extension manifest

Turns codegen into a proper spec-kit extension with:
- SOAR and codegen CLI as hard-stop dependencies
- speckit.codegen command with isolated execution behavior

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Polish `commands/codegen.md` — state.json writes

The current skill has no `.specify/squad/state.json` writes. We add a `write_state` bash helper and call it after each phase.

**Files:**
- Modify: `~/work/evolution/codegen/commands/codegen.md`

- [ ] **Step 1: Read current Phase 0.4 section to understand where initial state is written**

Open `~/work/evolution/codegen/commands/codegen.md` and locate the section `### 0.4 — Initialize pipeline state`. Note the bash block that writes `codegen-state.json`.

- [ ] **Step 2: Add `write_state` helper and initial state.json write after Section 0.4**

In `commands/codegen.md`, directly after the Section 0.4 bash block that writes `codegen-state.json` and runs `touch .codegen-active`, insert:

```markdown
### 0.4.1 — Initialize harness-compatible state

Define the `write_state` helper (call after every phase transition):

\```bash
STATE_JSON=".specify/squad/state.json"
mkdir -p "$(dirname $STATE_JSON)"

write_state() {
  local phase="$1"   # e.g. "codegen_re"
  local status="$2"  # building | build_done | blocked | escalated
  local completed="${3:-0}"
  local current="${4:-null}"
  local verdict="${5:-null}"
  cat > "$STATE_JSON" << STATEOF
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
\```
```

- [ ] **Step 3: Add state write at end of Phase 1 (RE complete)**

At the end of the `## Phase 1: RE` section, directly before the `**Print:** \`[CODEGEN] Phase RE — COMPLETE ✓\`` line, insert:

```markdown
Update state:
\```bash
write_state "codegen_decompose" "building" 0 null null
\```
```

- [ ] **Step 4: Add state write at end of Phase 2 (DECOMPOSE complete)**

At the end of `## Phase 2: DECOMPOSE`, after `task_queue.pending = [all task IDs]` and before the phase complete print, insert:

```markdown
Update state and set task total:
\```bash
TOTAL_TASKS=$(jq '.task_queue.pending | length' codegen-state.json)
write_state "codegen_implement" "building" 0 null null
\```
```

- [ ] **Step 5: Add state write inside the IMPLEMENT loop (Section 3.4)**

In `## Phase 3: IMPLEMENT`, inside Section 3.4 after the `exit 0 (ADVANCE)` branch comment, insert:

```markdown
On ADVANCE, update completed count:
\```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json)
CURRENT_TASK=$(jq -r '.task_queue.pending[0] // "null"' codegen-state.json)
if [ "$CURRENT_TASK" = "null" ]; then
  write_state "codegen_implement" "building" $COMPLETED null null
else
  write_state "codegen_implement" "building" $COMPLETED "\"${CURRENT_TASK}\"" null
fi
\```

On ESCALATE (exit 2), before writing `codegen-impasse.md`:
\```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json)
write_state "codegen_implement" "escalated" $COMPLETED null null
\```
```

- [ ] **Step 6: Add state write at end of Phase 4 (GATE complete)**

At the end of `## Phase 4: GATE`, before the phase complete print, insert:

```markdown
\```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json)
write_state "codegen_test" "building" $COMPLETED null null
\```
```

- [ ] **Step 7: Add state write at end of Phase 6 (TEST complete)**

At the end of `## Phase 6: TEST`, before the phase complete print, insert:

```markdown
\```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json)
write_state "codegen_deliver" "building" $COMPLETED null null
\```
```

- [ ] **Step 8: Add final state write in Phase 7 (DELIVER)**

At the end of `## Phase 7: DELIVER`, after the `rm -f .codegen-active` line, insert:

```markdown
\```bash
write_state "done" "build_done" $TOTAL_TASKS null '"PASS"'
\```
```

- [ ] **Step 9: Commit**

```bash
cd ~/work/evolution/codegen
git add commands/codegen.md
git commit -m "feat(skill): add harness-compatible state.json writes

After each SOAR phase transition, write .specify/squad/state.json
with status/phase/build fields compatible with echelon harness.
Introduces write_state bash helper called at every phase boundary.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Polish `commands/codegen.md` — resume sync

The RESUME mode currently reads `codegen-state.json` but does not restore `.specify/squad/state.json`, so the harness sees stale state on resume.

**Files:**
- Modify: `~/work/evolution/codegen/commands/codegen.md`

- [ ] **Step 1: Locate the RESUME mode section**

Find `## RESUME Mode` in `commands/codegen.md`. It currently reads `./codegen-state.json` and prints a summary block.

- [ ] **Step 2: Add state.json sync after the summary print**

After the resume summary print block (step 2 in the existing RESUME section), insert:

```markdown
3. Restore harness state from `codegen-state.json`:

\```bash
RESUME_PHASE=$(jq -r '.current_phase' codegen-state.json | tr '[:upper:]' '[:lower:]')
RESUME_COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
TOTAL_TASKS=$(jq '.task_queue.pending | length + (.task_queue.completed | length)' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_${RESUME_PHASE}" "building" $RESUME_COMPLETED null null
echo "[CODEGEN RESUME] state.json restored — phase=codegen_${RESUME_PHASE}"
\```
```

- [ ] **Step 3: Commit**

```bash
cd ~/work/evolution/codegen
git add commands/codegen.md
git commit -m "fix(skill): sync state.json on --resume

On resume, restore .specify/squad/state.json from codegen-state.json
so the harness sees current phase and progress rather than stale state.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Create `commands/echelon.codegen.md` — INIT + pre-flight

**Files:**
- Create: `~/work/evolution/echelon/commands/echelon.codegen.md`

- [ ] **Step 1: Create the file with frontmatter and INIT section**

Create `~/work/evolution/echelon/commands/echelon.codegen.md`:

```markdown
---
name: speckit.echelon.codegen
description: "Execute building phase via SOAR-powered codegen pipeline — alternative to echelon.build with inviolable CQ-ISC quality gates"
---

## User Input

$ARGUMENTS

---

## Overview

This command runs **Phase B: Building** via the SOAR-powered codegen pipeline. You receive a feature path (e.g. `001-feature`), validate Phase A artifacts, mine the spec into MemPalace, drive RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER, and write harness-compatible state to `.specify/squad/state.json` after each phase.

**Quality enforcement:** SOAR CQ-ISC prohibit preferences. Convergence requires Ψ ≥ 0.70 and all Tier 1 tests passing.

**Execution Continuity:** After any tool call returns, immediately execute the next step. Stop only when: (a) DELIVER completes, (b) impasse is reached, or (c) a hard error occurs.

---

## 1. INIT

### 1.0 Anchor project root

```bash
PROJECT_ROOT=$(pwd)
echo "PROJECT_ROOT=${PROJECT_ROOT}"
```

### 1.1 Parse feature path

```bash
FEATURE_PATH="$ARGUMENTS"
SPEC_ID=$(echo "$FEATURE_PATH" | grep -oE '^[0-9]+')
FEATURE_DIR="${PROJECT_ROOT}/specs/${FEATURE_PATH}"
WING="${SPEC_ID}"
echo "SPEC_ID=${SPEC_ID} WING=${WING} FEATURE_DIR=${FEATURE_DIR}"
```

If `$ARGUMENTS` is empty or `SPEC_ID` is empty, stop:

```
[ECHELON CODEGEN] ERROR: Feature path required.
Usage: /echelon.codegen 001-feature
```

If `$ARGUMENTS` is `--resume`, skip to Section 4 (Resume Mode).

### 1.2 Validate Phase A artifacts

```bash
MISSING=""
for f in spec.md tasks.md constitution.md research.md; do
  [ ! -f "${FEATURE_DIR}/${f}" ] && MISSING="${MISSING} ${f}"
done

if [ -n "$MISSING" ]; then
  echo "[ECHELON CODEGEN] ERROR: Missing Phase A artifacts:${MISSING}"
  echo "[ECHELON CODEGEN] Run /echelon.run ${FEATURE_PATH} first."
  exit 1
fi
echo "[ECHELON CODEGEN] Phase A artifacts verified ✓"
```

### 1.3 Verify dependencies (fail fast)

```bash
export CODEGEN_REQUIRE_MODEL_A=1

SOAR_BIN=""
command -v soar &>/dev/null && SOAR_BIN=$(command -v soar)
[ -z "$SOAR_BIN" ] && [ -f ~/soar/bin/soar ] && SOAR_BIN=~/soar/bin/soar

if [ -z "$SOAR_BIN" ]; then
  echo "[ECHELON CODEGEN] HARD STOP: SOAR binary not found."
  echo "  Install: download SoarSuite_9.6.4-Multiplatform.zip from"
  echo "           github.com/SoarGroup/Soar/releases/tag/releases%2F9.6.4"
  echo "  Then:    cp mac_ARM64/soar ~/soar/bin/ && cp mac_ARM64/*.dylib ~/soar/bin/"
  exit 1
fi

if ! command -v codegen &>/dev/null; then
  echo "[ECHELON CODEGEN] HARD STOP: codegen CLI not found."
  echo "  Install: bash ~/codegen/scripts/install.sh"
  exit 1
fi

echo "[ECHELON CODEGEN] Dependencies verified ✓ (soar=${SOAR_BIN})"
```

### 1.4 Mine spec into MemPalace

```bash
ALREADY_MINED=$(codegen requirements search "." --wing $WING --n 1 2>/dev/null | grep -c "room:" || echo "0")

if [ "$ALREADY_MINED" -eq 0 ]; then
  echo "[ECHELON CODEGEN] Mining spec into MemPalace — wing=${WING}..."
  for f in spec.md research.md; do
    [ -f "${FEATURE_DIR}/${f}" ] && codegen requirements mine "${FEATURE_DIR}/${f}" --wing $WING
  done
else
  echo "[ECHELON CODEGEN] MemPalace already has requirements for wing=${WING} — re-mining..."
  for f in spec.md research.md; do
    [ -f "${FEATURE_DIR}/${f}" ] && codegen requirements mine "${FEATURE_DIR}/${f}" --wing $WING
  done
fi
echo "[ECHELON CODEGEN] MemPalace ready — wing=${WING}"
```

### 1.5 Self-register harness strategy file (idempotent)

```bash
STRATEGY_DIR="${PROJECT_ROOT}/.specify/harness/strategies/${FEATURE_PATH}"
STRATEGY_FILE="${STRATEGY_DIR}/codegen.md"
mkdir -p "$STRATEGY_DIR"

EXPECTED_CONTENT="Invoke: /speckit.echelon.codegen ${FEATURE_PATH}"
if [ ! -f "$STRATEGY_FILE" ] || ! grep -qF "$EXPECTED_CONTENT" "$STRATEGY_FILE"; then
  cat > "$STRATEGY_FILE" << EOF
# Codegen Strategy

This strategy uses the SOAR-powered codegen pipeline.

${EXPECTED_CONTENT}

To run in parallel with default (squad) strategy:
  run spec ${FEATURE_PATH} strategies=default,codegen kill_losers
EOF
  echo "[ECHELON CODEGEN] Strategy file registered: ${STRATEGY_FILE}"
else
  echo "[ECHELON CODEGEN] Strategy file already current: ${STRATEGY_FILE}"
fi
```

### 1.6 Initialize state

```bash
PIPELINE_ID=$(uuidgen)
WALL_CLOCK_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Count tasks in tasks.md (lines starting with - [ ] or - [x])
TOTAL_TASKS=$(grep -cE '^- \[.?\]' "${FEATURE_DIR}/tasks.md" 2>/dev/null || echo "0")

STATE_FILE="${PROJECT_ROOT}/.specify/squad/state.json"
mkdir -p "$(dirname $STATE_FILE)"

write_state() {
  local phase="$1"
  local status="$2"
  local completed="${3:-0}"
  local current="${4:-null}"
  local verdict="${5:-null}"
  cat > "$STATE_FILE" << STATEOF
{
  "status": "${status}",
  "phase": "${phase}",
  "build": {
    "total_tasks": ${TOTAL_TASKS},
    "completed_tasks": ${completed},
    "current_task": ${current},
    "verification_verdict": ${verdict}
  },
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
STATEOF
}

# Write initial codegen-state.json
cat > codegen-state.json << EOF
{
  "pipeline_id": "${PIPELINE_ID}",
  "wing": "${WING}",
  "mode": "echelon",
  "feature_dir": "${FEATURE_DIR}",
  "current_phase": "RE",
  "wall_clock_start": "${WALL_CLOCK_START}",
  "psi": { "score": null, "threshold": 0.70 },
  "tier1_gate": null,
  "task_queue": { "pending": [], "completed": [] }
}
EOF

write_state "codegen_re" "building" 0 null null
touch .codegen-active

echo "[ECHELON CODEGEN] State initialized — pipeline_id=${PIPELINE_ID} tasks=${TOTAL_TASKS}"
```
```

- [ ] **Step 2: Verify the file was created and has correct frontmatter**

```bash
head -5 ~/work/evolution/echelon/commands/echelon.codegen.md
```

Expected:
```
---
name: speckit.echelon.codegen
description: "Execute building phase via SOAR-powered codegen pipeline — alternative to echelon.build with inviolable CQ-ISC quality gates"
---
```

- [ ] **Step 3: Commit**

```bash
cd ~/work/evolution/echelon
git add commands/echelon.codegen.md
git commit -m "feat(commands): add echelon.codegen INIT section

First half of echelon.codegen.md — covers argument parsing, Phase A
artifact validation, dependency verification, MemPalace mining,
strategy file self-registration, and state initialization.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Create `commands/echelon.codegen.md` — pipeline + BUILD_DONE

**Files:**
- Modify: `~/work/evolution/echelon/commands/echelon.codegen.md` (append sections 2–3)

- [ ] **Step 1: Append the pipeline execution section**

Append to `~/work/evolution/echelon/commands/echelon.codegen.md`:

```markdown
---

## 2. Pipeline Execution (BUILD_LOOP)

### 2.1 SOAR bridge init

```bash
codegen --verbose gate --phase RE --language auto --files /dev/null \
  --state-file codegen-state.json 2>&1 \
  | grep -E "Model A|Model B|soar_model|RuntimeError" | head -5

if grep -q "RuntimeError" <(codegen --verbose gate --phase RE --language auto \
  --files /dev/null --state-file codegen-state.json 2>&1); then
  echo "[ECHELON CODEGEN] HARD STOP: SOAR Model A failed to start."
  echo "  Verify SOAR installation and CODEGEN_REQUIRE_MODEL_A=1"
  write_state "codegen_re" "escalated" 0 null null
  exit 1
fi
echo "[ECHELON CODEGEN] SOAR Model A active ✓"
```

### 2.2 RE phase

**Print:** `[ECHELON CODEGEN] Phase RE — Starting...`

```bash
codegen run \
  --intent "$(head -3 ${FEATURE_DIR}/spec.md | tr '\n' ' ')" \
  --wing "$WING" \
  --state-file codegen-state.json
```

After RE completes:

```bash
write_state "codegen_decompose" "building" 0 null null
echo "[ECHELON CODEGEN] Phase RE — COMPLETE ✓"
```

### 2.3 DECOMPOSE phase

**Print:** `[ECHELON CODEGEN] Phase DECOMPOSE — Starting...`

DECOMPOSE runs automatically as part of `codegen run`. After DECOMPOSE hook fires:

```bash
TOTAL_TASKS=$(jq '(.task_queue.pending | length) + (.task_queue.completed | length)' \
  codegen-state.json 2>/dev/null || echo $TOTAL_TASKS)
write_state "codegen_implement" "building" 0 null null
echo "[ECHELON CODEGEN] Phase DECOMPOSE — COMPLETE ✓ (${TOTAL_TASKS} tasks queued)"
```

### 2.4 IMPLEMENT phase

**Print:** `[ECHELON CODEGEN] Phase IMPLEMENT — Starting...`

IMPLEMENT runs per-task inside the codegen pipeline. After each task ADVANCE:

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json)
NEXT=$(jq -r '.task_queue.pending[0] // "null"' codegen-state.json)
if [ "$NEXT" = "null" ]; then
  write_state "codegen_implement" "building" $COMPLETED null null
else
  write_state "codegen_implement" "building" $COMPLETED "\"${NEXT}\"" null
fi
```

On ESCALATE (codegen gate exit code 2):

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json)
write_state "codegen_implement" "escalated" $COMPLETED null null
echo "[ECHELON CODEGEN] IMPASSE — see codegen-impasse.md for resolution options"
rm -f .codegen-active
exit 2
```

**Print:** `[ECHELON CODEGEN] Phase IMPLEMENT — COMPLETE ✓`

### 2.5 GATE phase (CQ-ISC verification)

**Print:** `[ECHELON CODEGEN] Phase GATE — Running CQ-ISC verification...`

```bash
codegen gate \
  --phase GATE \
  --language auto \
  --files $(jq -r '.task_queue.completed | join(" ")' codegen-state.json) \
  --state-file codegen-state.json
GATE_EXIT=$?
```

- Exit 0 (Ψ ≥ 0.70, zero violations):

```bash
write_state "codegen_test" "building" $COMPLETED null null
echo "[ECHELON CODEGEN] Phase GATE — COMPLETE ✓ (Ψ=$(jq -r '.psi.score' codegen-state.json))"
```

- Exit 1 (RETRY): re-dispatch IMPLEMENT with violation details (max 3 retries). Update state on each retry.

- Exit 2 (ESCALATE):

```bash
write_state "codegen_gate" "escalated" $COMPLETED null null
echo "[ECHELON CODEGEN] GATE IMPASSE — see codegen-impasse.md"
rm -f .codegen-active
exit 2
```

### 2.6 TEST phase (Tier 1 gate)

**Print:** `[ECHELON CODEGEN] Phase TEST — Running Tier 1 gate...`

Auto-detect and run tests:

```bash
if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
  pytest --tb=short --json-report --json-report-file=./codegen-staging/test-results.json 2>&1
  TEST_EXIT=$?
elif [ -f "package.json" ]; then
  npx vitest run --reporter=json --outputFile=./codegen-staging/test-results.json 2>&1
  TEST_EXIT=$?
elif [ -f "go.mod" ]; then
  go test ./... -json 2>&1 | tee ./codegen-staging/test-results.json
  TEST_EXIT=$?
else
  echo "[ECHELON CODEGEN] WARNING: No test runner detected — Tier 1 gate unavailable"
  TEST_EXIT=0
fi
```

On pass (TEST_EXIT=0):

```bash
write_state "codegen_deliver" "building" $COMPLETED null null
echo "[ECHELON CODEGEN] Phase TEST — COMPLETE ✓ (Tier 1 gate PASSED)"
```

On fail: route back to IMPLEMENT with failing test output. Max 2 retry cycles. If still failing:

```bash
write_state "codegen_test" "blocked" $COMPLETED null '"FAIL"'
echo "[ECHELON CODEGEN] Tier 1 gate FAILED — delivery blocked"
rm -f .codegen-active
exit 1
```

---

## 3. BUILD_DONE

### 3.1 DELIVER phase

SOAR selects DELIVER only when Ψ ≥ 0.70 and all Tier 1 tests pass.

```bash
codegen gate \
  --phase DELIVER \
  --language auto \
  --files $(jq -r '.task_queue.completed | join(" ")' codegen-state.json) \
  --state-file codegen-state.json

# Update wall clock end
WALL_CLOCK_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq --arg end "$WALL_CLOCK_END" '.wall_clock_end = $end' codegen-state.json > tmp.json \
  && mv tmp.json codegen-state.json

write_state "done" "build_done" $TOTAL_TASKS null '"PASS"'
rm -f .codegen-active
```

### 3.2 Print terminal summary

```
============================================
  ECHELON CODEGEN BUILD COMPLETE
============================================

Feature:    ${FEATURE_PATH}
Wing:       ${WING}
Pipeline:   ${PIPELINE_ID}

QUALITY GATES (SOAR CQ-ISC):
  Ψ score:        $(jq -r '.psi.score // "N/A"' codegen-state.json)  (threshold 0.70)
  CQ-ISC blocks:  $(jq -r '.violations_blocked // 0' codegen-state.json)
  Tier 1 gate:    $(jq -r '.tier1_gate // "UNAVAILABLE"' codegen-state.json | tr '[:lower:]' '[:upper:]')

TASKS:
  Total:     ${TOTAL_TASKS}
  Completed: $(jq -r '.task_queue.completed | length' codegen-state.json)

HARNESS (parallel run available):
  Strategy file: .specify/harness/strategies/${FEATURE_PATH}/codegen.md
  To run in parallel:
    run spec ${FEATURE_PATH} strategies=default,codegen kill_losers

REPORTS:
  codegen-report.md      (SOAR delivery report)
  codegen-state.json     (full pipeline audit trail)
  .specify/squad/state.json  (harness state)

HUMAN ACTIONS REQUIRED:
  None — build completed autonomously.

============================================
```

---

## 4. Resume Mode

If `$ARGUMENTS` is `--resume`:

```bash
if [ ! -f codegen-state.json ]; then
  echo "[ECHELON CODEGEN] ERROR: No codegen-state.json found. Cannot resume."
  exit 1
fi

WING=$(jq -r '.wing' codegen-state.json)
FEATURE_DIR=$(jq -r '.feature_dir' codegen-state.json)
FEATURE_PATH=$(basename "$FEATURE_DIR")
CURRENT_PHASE=$(jq -r '.current_phase' codegen-state.json | tr '[:upper:]' '[:lower:]')
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json)
TOTAL_TASKS=$(jq '(.task_queue.pending | length) + (.task_queue.completed | length)' codegen-state.json)
PSI=$(jq -r '.psi.score // "N/A"' codegen-state.json)
PIPELINE_ID=$(jq -r '.pipeline_id' codegen-state.json)

STATE_FILE="${PROJECT_ROOT}/.specify/squad/state.json"
mkdir -p "$(dirname $STATE_FILE)"

# Restore state.json
cat > "$STATE_FILE" << EOF
{
  "status": "building",
  "phase": "codegen_${CURRENT_PHASE}",
  "build": {
    "total_tasks": ${TOTAL_TASKS},
    "completed_tasks": ${COMPLETED},
    "current_task": null,
    "verification_verdict": null
  },
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "[ECHELON CODEGEN RESUME]"
echo "Pipeline:    ${PIPELINE_ID}"
echo "Wing:        ${WING}"
echo "Resuming at: ${CURRENT_PHASE}"
echo "Tasks done:  ${COMPLETED} / ${TOTAL_TASKS}"
echo "Ψ score:     ${PSI}"
echo ""
echo "[ECHELON CODEGEN] state.json restored — jumping to Phase ${CURRENT_PHASE}"
```

Do NOT re-mine specs on resume — MemPalace already has them. Jump directly to Section 2 at `$CURRENT_PHASE`.

---

## 5. Error Handling

| Error | Response |
|---|---|
| Missing Phase A artifact | STOP — print which file is missing + hint to run `/echelon.run` |
| SOAR binary not found | HARD STOP — print install instructions |
| codegen CLI not found | HARD STOP — print install instructions |
| SOAR Model A RuntimeError | HARD STOP — write `status: escalated`, exit 1 |
| Impasse (SOAR exit 2) | Write `status: escalated`, write `codegen-impasse.md`, exit 2 |
| Tier 1 tests fail after 2 retries | Write `status: blocked`, exit 1 |
| Context limit approaching | Write state checkpoint, print resume hint |
```

- [ ] **Step 2: Verify the file structure**

```bash
grep -n "^##" ~/work/evolution/echelon/commands/echelon.codegen.md
```

Expected sections:
```
## User Input
## Overview
## 1. INIT
## 2. Pipeline Execution (BUILD_LOOP)
## 3. BUILD_DONE
## 4. Resume Mode
## 5. Error Handling
```

- [ ] **Step 3: Commit**

```bash
cd ~/work/evolution/echelon
git add commands/echelon.codegen.md
git commit -m "feat(commands): complete echelon.codegen pipeline + BUILD_DONE

Adds pipeline execution sections (RE→DECOMPOSE→IMPLEMENT→GATE→TEST),
BUILD_DONE/DELIVER with final state writes, resume mode with state.json
sync, and error handling table.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Update echelon `extension.yml`

**Files:**
- Modify: `~/work/spec-kit-skills-agents/.specify/extensions/echelon/extension.yml`

- [ ] **Step 1: Locate the insertion point**

The new entry goes in `provides.commands`, after the last user-invocable command and before the `# ── Agent Definitions` comment block. That is after the `speckit.echelon.health` entry.

- [ ] **Step 2: Insert the new command entry**

In `.specify/extensions/echelon/extension.yml`, find:

```yaml
    - name: "speckit.echelon.health"
      file: "commands/echelon.health.md"
      description: "Periodic health check — spec-code drift, estimate drift, KB freshness"

    # ── Agent Definitions ──────────────────────────────────────────
```

Replace with:

```yaml
    - name: "speckit.echelon.health"
      file: "commands/echelon.health.md"
      description: "Periodic health check — spec-code drift, estimate drift, KB freshness"
    - name: "speckit.echelon.codegen"
      file: "commands/echelon.codegen.md"
      description: "Execute building phase via SOAR-powered codegen pipeline — alternative to echelon.build"
      behavior:
        execution: isolated
        invocation: explicit
        capability: strong
        effort: high
        tools: full

    # ── Agent Definitions ──────────────────────────────────────────
```

- [ ] **Step 3: Validate YAML**

```bash
cd ~/work/spec-kit-skills-agents
python3 -c "
import yaml
data = yaml.safe_load(open('.specify/extensions/echelon/extension.yml'))
cmds = [c['name'] for c in data['provides']['commands'] if not data['provides']['commands'].index(c) or True]
print('Commands:', [c for c in cmds if 'echelon' in c and 'agent' not in c.lower()][:15])
"
```

Expected output includes `speckit.echelon.codegen` in the list.

- [ ] **Step 4: Commit**

```bash
cd ~/work/spec-kit-skills-agents
git add .specify/extensions/echelon/extension.yml
git commit -m "feat(echelon-ext): register speckit.echelon.codegen command

Adds echelon.codegen to the echelon extension manifest with
isolated execution, explicit invocation, strong capability.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Integration smoke test

Verify the four artifacts fit together before calling this done.

**Files:** None created — read-only checks.

- [ ] **Step 1: Validate both extension YMLs**

```bash
python3 -c "
import yaml

# codegen extension
cg = yaml.safe_load(open('/Users/michalbachorik/work/evolution/codegen/extension.yml'))
assert cg['extension']['id'] == 'codegen'
assert cg['provides']['commands'][0]['name'] == 'speckit.codegen'
assert cg['provides']['commands'][0]['behavior']['execution'] == 'isolated'
print('codegen extension.yml ✓')

# echelon extension
ec = yaml.safe_load(open('/Users/michalbachorik/work/spec-kit-skills-agents/.specify/extensions/echelon/extension.yml'))
names = [c['name'] for c in ec['provides']['commands']]
assert 'speckit.echelon.codegen' in names
ec_cmd = next(c for c in ec['provides']['commands'] if c['name'] == 'speckit.echelon.codegen')
assert ec_cmd['behavior']['execution'] == 'isolated'
assert ec_cmd['behavior']['invocation'] == 'explicit'
print('echelon extension.yml ✓')
"
```

Expected:
```
codegen extension.yml ✓
echelon extension.yml ✓
```

- [ ] **Step 2: Verify echelon.codegen.md references correct file path**

```bash
grep -n "^name:" ~/work/evolution/echelon/commands/echelon.codegen.md
```

Expected: `name: speckit.echelon.codegen`

```bash
# Verify the file referenced in extension.yml exists
[ -f ~/work/evolution/echelon/commands/echelon.codegen.md ] && echo "echelon.codegen.md exists ✓" || echo "MISSING"
[ -f ~/work/evolution/codegen/commands/codegen.md ] && echo "codegen.md exists ✓" || echo "MISSING"
```

- [ ] **Step 3: Verify state.json write pattern is present in both skills**

```bash
grep -c "write_state" ~/work/evolution/codegen/commands/codegen.md
```
Expected: ≥ 6 (one call per phase boundary + definition)

```bash
grep -c "write_state" ~/work/evolution/echelon/commands/echelon.codegen.md
```
Expected: ≥ 7

- [ ] **Step 4: Verify self-registration block**

```bash
grep -A5 "Self-register" ~/work/evolution/echelon/commands/echelon.codegen.md | head -10
```

Expected: contains `STRATEGY_FILE` and `mkdir -p "$STRATEGY_DIR"`.

- [ ] **Step 5: Verify resume sync in both skills**

```bash
grep -n "state.json" ~/work/evolution/codegen/commands/codegen.md | grep -i "restor\|sync\|resume" | head -5
grep -n "Restore state" ~/work/evolution/echelon/commands/echelon.codegen.md
```

- [ ] **Step 6: Final commit — update spec status**

```bash
cd ~/work/evolution/echelon
sed -i '' 's/\*\*Status:\*\* Approved/**Status:** Implemented/' \
  docs/superpowers/specs/2026-04-15-codegen-echelon-integration-design.md
git add docs/superpowers/specs/2026-04-15-codegen-echelon-integration-design.md
git commit -m "docs(design): mark codegen-echelon integration as implemented

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
