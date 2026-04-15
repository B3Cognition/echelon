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
