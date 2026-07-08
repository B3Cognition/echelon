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

  # constitution.md is a published Phase A snapshot. Do not copy or repair it
  # from .specify/memory here; rerun Phase A finalization if the snapshot is
  # missing or stale.

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
        # Keep constitution.md as a published Phase A snapshot. Do not copy or
        # repair it from .specify/memory after merge.
      else
        echo "[RECOVERY] Merge failed — branch ${FEATURE_BRANCH} may not be accessible"
      fi
    fi
  fi

  if [ -n "${MISSING}" ]; then
    echo "[ECHELON CODEGEN] ERROR: Missing Phase A artifacts:${MISSING}"
    echo "[ECHELON CODEGEN] Run echelon spec continue for ${FEATURE_PATH} first so Phase A republishes build inputs."
    exit 1
  fi

  if grep -qE '\[PROJECT_NAME\]|\[PRINCIPLE_[0-9]+_NAME\]|\[CONSTITUTION_VERSION\]|\[RATIFICATION_DATE\]|\[LAST_AMENDED_DATE\]' "${FEATURE_DIR}/constitution.md"; then
    echo "[ECHELON CODEGEN] ERROR: constitution.md contains unresolved template markers."
    echo "[ECHELON CODEGEN] Run echelon spec continue for ${FEATURE_PATH} first so CHIEF repairs the canonical constitution and Phase A republishes the snapshot."
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

### A.4 Set harness state file

```bash
# Derive from HARNESS_BUILD_STATUS_FILE when running inside echelon-harness.
# Layout: {build_dir}/worktrees/{strategy}/iter-{n}/.harness-build-status.json
# State:  {build_dir}/state/codegen.json
if [ -n "${HARNESS_BUILD_STATUS_FILE:-}" ]; then
  _WT=$(dirname "${HARNESS_BUILD_STATUS_FILE}")  # iter-{n}/
  _WT=$(dirname "${_WT}")                         # {strategy}/
  _WT=$(dirname "${_WT}")                         # worktrees/
  _BUILD_DIR=$(dirname "${_WT}")                  # build-{id}/
  HARNESS_STATE_FILE="${_BUILD_DIR}/state/codegen.json"
  mkdir -p "${_BUILD_DIR}/state"
else
  HARNESS_STATE_FILE=""
fi
echo "[ECHELON CODEGEN] Harness state file: ${HARNESS_STATE_FILE:-not set (standalone mode)}"
```

### A.5 Validate deploy infrastructure

```bash
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
_DEPLOY_ROOT="${PROJECT_ROOT}"

# In a harness worktree, PROJECT_ROOT is the worktree path — .specify/ and deploy
# config live in the main checkout, not the worktree. Derive the main project root
# from HARNESS_BUILD_STATUS_FILE (injected by the harness at worktree creation):
#   .harness-build-status.json → iter-{n}/ → {strategy}/ → worktrees/ → build-{id}/ → runs/ → project root
if [ ! -d "${ECHELON_EXT}" ] && [ -n "${HARNESS_BUILD_STATUS_FILE:-}" ]; then
  _p=$(dirname "${HARNESS_BUILD_STATUS_FILE}")
  _p=$(dirname "${_p}")
  _p=$(dirname "${_p}")
  _p=$(dirname "${_p}")
  _p=$(dirname "${_p}")
  _p=$(dirname "${_p}")
  if [ -d "${_p}/.specify/extensions/echelon" ]; then
    ECHELON_EXT="${_p}/.specify/extensions/echelon"
    _DEPLOY_ROOT="${_p}"
  fi
fi

bash "${ECHELON_EXT}/scripts/bash/validate-deploy.sh" "${_DEPLOY_ROOT}"
```

If exit code is non-zero, HARD STOP. Always follow the error output fix instructions. Do not launch harness.

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
DEPLOY_STATE_FILE="${_DEPLOY_ROOT}/.specify/squad/deploy-state.json"
for base in runs squad; do
  current_file="${_DEPLOY_ROOT}/${base}/.current"
  if [ -f "${current_file}" ]; then
    run_id=$(tr -d '[:space:]' < "${current_file}")
    candidate="${_DEPLOY_ROOT}/${base}/${run_id}/deploy-state.json"
    if [ -n "${run_id}" ] && [ -d "$(dirname "${candidate}")" ]; then
      DEPLOY_STATE_FILE="${candidate}"
      break
    fi
  fi
done

DEPLOY_STATE=$(cat "${DEPLOY_STATE_FILE}" 2>/dev/null || echo '')
DEPLOY_APP=$(echo "${DEPLOY_STATE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('app',''))" 2>/dev/null || echo '')
DEPLOY_TYPE=$(echo "${DEPLOY_STATE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('type',''))" 2>/dev/null || echo '')

if [ "${DEPLOY_TYPE}" = "http" ] && [ -n "${DEPLOY_APP}" ]; then
  echo "[ECHELON CODEGEN] Applying SPA base path for ${DEPLOY_APP}..."
  bash "${ECHELON_EXT}/scripts/bash/fix-spa-base.sh" "${PROJECT_ROOT}" "${DEPLOY_APP}"
  # Only stage files the SPA fix actually modified (tracked files only).
  # Using `git add -u` avoids accidentally staging untracked files written by
  # earlier preamble steps (e.g. the strategy file).
  if ! git -C "${PROJECT_ROOT}" diff --quiet; then
    git -C "${PROJECT_ROOT}" add -u
    git -C "${PROJECT_ROOT}" commit -m "chore: apply SPA base path for ${DEPLOY_APP} [skip ci]"
    echo "[ECHELON CODEGEN] SPA base path committed — safe from merge overwrites"
  else
    echo "[ECHELON CODEGEN] SPA base path — no tracked files changed, skipping commit"
  fi
fi
```
