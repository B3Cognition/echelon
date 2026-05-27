# Phase: codegen-A-preamble
# Source: echelon.codegen.md §Phase A — Echelon Preamble
# Read by: speckit-echelon-orchestrator (ORCHESTRATOR) before starting codegen pipeline (skip entirely on --resume)

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

  # constitution.md lives in .specify/memory/ — copy it into the spec dir if missing
  if echo "${MISSING}" | grep -q "constitution\.md"; then
    if [ -f "${PROJECT_ROOT}/.specify/memory/constitution.md" ]; then
      cp "${PROJECT_ROOT}/.specify/memory/constitution.md" \
         "${FEATURE_DIR}/constitution.md"
      echo "[RECOVERY] constitution.md copied from .specify/memory/ ✓"
      MISSING=$(echo "${MISSING}" | sed 's/ constitution\.md//')
    fi
  fi

  # If spec.md (or other core artifacts) are still missing, the worktree may not
  # have the spec branch merged in. The harness should have used the feature branch
  # directly (via base_branch in create_worktree), so missing spec.md here means
  # either the feature branch was never committed or the harness used legacy mode.
  # Auto-recover: merge the feature branch if discoverable.
  if echo "${MISSING}" | grep -q "spec\.md"; then
    FEATURE_BRANCH=$(git -C "${PROJECT_ROOT}" branch --list "${SPEC_ID}-*" \
                     | head -1 | tr -d '* ' | xargs)
    if [ -z "${FEATURE_BRANCH}" ]; then
      # Try remote
      FEATURE_BRANCH=$(git -C "${PROJECT_ROOT}" branch -r --list "origin/${SPEC_ID}-*" \
                       | head -1 | tr -d '* ' | sed 's|origin/||' | xargs)
    fi
    if [ -n "${FEATURE_BRANCH}" ]; then
      echo "[RECOVERY] spec.md missing — merging feature branch ${FEATURE_BRANCH}..."
      if git -C "${PROJECT_ROOT}" merge --no-ff --no-edit "${FEATURE_BRANCH}" 2>/dev/null \
         || git -C "${PROJECT_ROOT}" merge --no-ff --no-edit "origin/${FEATURE_BRANCH}" 2>/dev/null; then
        echo "[RECOVERY] Feature branch merged ✓"
        MISSING=""
        for f in spec.md tasks.md constitution.md research.md; do
          [ ! -f "${FEATURE_DIR}/${f}" ] && MISSING="${MISSING} ${f}"
        done
        # Try constitution once more after merge
        if echo "${MISSING}" | grep -q "constitution\.md"; then
          if [ -f "${PROJECT_ROOT}/.specify/memory/constitution.md" ]; then
            cp "${PROJECT_ROOT}/.specify/memory/constitution.md" "${FEATURE_DIR}/constitution.md"
            echo "[RECOVERY] constitution.md copied from .specify/memory/ ✓"
            MISSING=$(echo "${MISSING}" | sed 's/ constitution\.md//')
          fi
        fi
      else
        echo "[RECOVERY] Merge failed — branch ${FEATURE_BRANCH} may not be accessible"
      fi
    fi
  fi

  if [ -n "${MISSING}" ]; then
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

### A.5 Validate deploy infrastructure

```bash
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
bash "${ECHELON_EXT}/scripts/bash/validate-deploy.sh" "${PROJECT_ROOT}"
```

If exit code is non-zero, HARD STOP. Do not launch harness. The error output contains the fix instructions.

### A.6 Register harness strategy file (idempotent, skip on resume)

```bash
if [ "$RESUME_MODE" -eq 0 ]; then
  STRATEGY_DIR="${PROJECT_ROOT}/runs/strategies/${FEATURE_PATH}"
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

### A.7 Load build lessons (skip on resume)

```bash
LESSONS_FILE="${FEATURE_DIR}/lessons.md"
PITFALLS_FILE="${PROJECT_ROOT}/.specify/knowledge-base/pitfalls.yaml"

LESSONS_CONTENT=""
[ -f "${LESSONS_FILE}" ] && LESSONS_CONTENT=$(cat "${LESSONS_FILE}")
[ -f "${PITFALLS_FILE}" ] && LESSONS_CONTENT="${LESSONS_CONTENT}
$(cat ${PITFALLS_FILE})"

echo "[ECHELON CODEGEN] Lessons loaded: $(echo "${LESSONS_CONTENT}" | grep -c '^## Lesson' || echo 0) entries"
```

If `LESSONS_CONTENT` is non-empty, translate each `INVARIANT:` line into a SOAR CQ-ISC prohibit preference in Phase 0. These are not advisory — they are enforced by the GATE phase the same as any other prohibit preference. Record in EPMEM that lessons were loaded.

Also run the SPA base path fix and stage it before any SOAR phase starts:

```bash
DEPLOY_STATE=$(cat "${PROJECT_ROOT}/.specify/squad/deploy-state.json" 2>/dev/null || echo '')
DEPLOY_APP=$(echo "${DEPLOY_STATE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('app',''))" 2>/dev/null || echo '')
DEPLOY_TYPE=$(echo "${DEPLOY_STATE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('type',''))" 2>/dev/null || echo '')

if [ "${DEPLOY_TYPE}" = "http" ] && [ -n "${DEPLOY_APP}" ]; then
  echo "[ECHELON CODEGEN] Applying SPA base path for ${DEPLOY_APP}..."
  bash "${ECHELON_EXT}/scripts/bash/fix-spa-base.sh" "${PROJECT_ROOT}" "${DEPLOY_APP}"
  # Only stage files the SPA fix actually modified (tracked files only).
  # Using `git add -u` avoids accidentally staging untracked files written by
  # earlier preamble steps (e.g. the strategy file, constitution recovery).
  if ! git -C "${PROJECT_ROOT}" diff --quiet; then
    git -C "${PROJECT_ROOT}" add -u
    git -C "${PROJECT_ROOT}" commit -m "chore: apply SPA base path for ${DEPLOY_APP} [skip ci]"
    echo "[ECHELON CODEGEN] SPA base path committed — safe from merge overwrites"
  else
    echo "[ECHELON CODEGEN] SPA base path — no tracked files changed, skipping commit"
  fi
fi
```
