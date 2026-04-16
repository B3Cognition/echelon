---
name: speckit.echelon.codegen
description: "Execute building phase via SOAR-powered codegen pipeline — echelon wrapper around /codegen"
---

## User Input

$ARGUMENTS

---

## Overview

Thin echelon wrapper. Validates Phase A artifacts, mines the spec into MemPalace, self-registers
the harness strategy file, then delegates the entire pipeline to the `codegen` skill.

The `codegen` skill owns RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER.
This wrapper sets `HARNESS_STATE_FILE` so `codegen` writes echelon-harness-compatible
state to `.specify/squad/state.json` after each phase transition.

**Execution Continuity:** After each Bash tool call, immediately execute the next step
without pausing unless a hard stop condition is reached.

---

## 1. Parse and Validate

### 1.1 Anchor project root and parse feature path

```bash
PROJECT_ROOT=$(pwd)
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
  echo "  Install: bash ~/codegen/scripts/install.sh"
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
else
  echo "[ECHELON CODEGEN] Re-mining updated specs — wing=${WING}..."
fi

for f in spec.md research.md; do
  [ -f "${FEATURE_DIR}/${f}" ] && codegen requirements mine "${FEATURE_DIR}/${f}" --wing $WING
done
echo "[ECHELON CODEGEN] MemPalace ready — wing=${WING}"
```

### 1.5 Self-register harness strategy file (idempotent)

```bash
STRATEGY_DIR="${PROJECT_ROOT}/.specify/harness/strategies/${FEATURE_PATH}"
STRATEGY_FILE="${STRATEGY_DIR}/codegen.md"
mkdir -p "$STRATEGY_DIR"

if [ ! -f "$STRATEGY_FILE" ] || ! grep -qF "command: echelon codegen" "$STRATEGY_FILE"; then
  cat > "$STRATEGY_FILE" << EOF
---
command: echelon codegen
---
# Codegen Strategy

This strategy uses the SOAR-powered codegen pipeline.
Invoke: /speckit.echelon.codegen ${FEATURE_PATH}

To run in parallel with default (squad) strategy:
  run spec ${FEATURE_PATH} strategies=default,codegen kill_losers
EOF
  echo "[ECHELON CODEGEN] Strategy file registered: ${STRATEGY_FILE}"
else
  echo "[ECHELON CODEGEN] Strategy file already current: ${STRATEGY_FILE}"
fi
```

### 1.6 Set HARNESS_STATE_FILE (harness integration protocol)

Write `.codegen-harness-env` so the `codegen` pipeline can locate the harness state file
across bash tool calls (bash env does not persist between tool calls).

```bash
HARNESS_STATE_FILE="${PROJECT_ROOT}/.specify/squad/state.json"
mkdir -p "$(dirname "$HARNESS_STATE_FILE")"
echo "HARNESS_STATE_FILE=${HARNESS_STATE_FILE}" > .codegen-harness-env
echo "[ECHELON CODEGEN] Harness state file: ${HARNESS_STATE_FILE}"
```

---

## 2. Delegate to Codegen Pipeline

Invoke the `codegen` skill with the feature spec files as input:

```
/speckit.codegen specs/${FEATURE_PATH}/*.md "$(head -1 ${FEATURE_DIR}/spec.md | sed 's/^#* *//')"
```

The `codegen` pipeline reads `.codegen-harness-env` (written in Step 1.6) to locate
`HARNESS_STATE_FILE` and writes `.specify/squad/state.json` after each phase transition.
All pipeline phases (RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER) run inside
`codegen`. This command's job is done once delegation starts.

On codegen impasse (`codegen-impasse.md` written, exit code 2): do not enter a feedback
loop. Report the impasse path and stop.

---

## 4. Resume Mode

If `$ARGUMENTS` is `--resume`:

```bash
if [ ! -f codegen-state.json ]; then
  echo "[ECHELON CODEGEN] ERROR: No codegen-state.json found. Cannot resume."
  exit 1
fi

PROJECT_ROOT=$(pwd)
HARNESS_STATE_FILE="${PROJECT_ROOT}/.specify/squad/state.json"
mkdir -p "$(dirname "$HARNESS_STATE_FILE")"
echo "HARNESS_STATE_FILE=${HARNESS_STATE_FILE}" > .codegen-harness-env
echo "[ECHELON CODEGEN] Harness env restored for resume."
```

Then invoke the codegen pipeline in resume mode:

```
/speckit.codegen --resume
```

---

## 5. Error Handling

| Error | Response |
|---|---|
| Missing Phase A artifact | STOP — print which file is missing + hint to run `/echelon.run` |
| SOAR binary not found | HARD STOP — print install instructions |
| codegen CLI not found | HARD STOP — print install instructions |
| Impasse (codegen exit 2) | Stop and report `codegen-impasse.md` path — do NOT enter feedback loop |
