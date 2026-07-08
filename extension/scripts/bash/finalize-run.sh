#!/usr/bin/env bash
# finalize-run.sh — Commit spec artifacts to feature branch and return to default branch.
# Called as the terminal step of echelon spec run (phase4-document §12.10b).
# Usage: finalize-run.sh <PROJECT_ROOT> <SPEC_ID> <FEATURE_NAME> <RUN_ID>
set -euo pipefail

PROJECT_ROOT="${1:?PROJECT_ROOT required}"
SPEC_ID="${2:?SPEC_ID required}"
FEATURE_NAME="${3:?FEATURE_NAME required}"
RUN_ID="${4:?RUN_ID required}"

SPEC_DIR="${PROJECT_ROOT}/specs/${SPEC_ID}-${FEATURE_NAME}"

echo "[FINALIZE] Committing spec artifacts for ${SPEC_ID}-${FEATURE_NAME}..."

# ── 1. Copy constitution into spec dir ────────────────────────────────────────
CONSTITUTION_SRC="${PROJECT_ROOT}/.specify/memory/constitution.md"
CONSTITUTION_DST="${SPEC_DIR}/constitution.md"
if [ -f "${CONSTITUTION_SRC}" ]; then
  if grep -qE '\[PROJECT_NAME\]|\[PRINCIPLE_[0-9]+_NAME\]|\[CONSTITUTION_VERSION\]|\[RATIFICATION_DATE\]|\[LAST_AMENDED_DATE\]' "${CONSTITUTION_SRC}"; then
    echo "[FINALIZE] ERROR: .specify/memory/constitution.md contains unresolved template markers"
    echo "[FINALIZE] Run echelon spec continue so CHIEF invokes speckit.constitution before publishing the snapshot"
    exit 1
  fi
  cp "${CONSTITUTION_SRC}" "${CONSTITUTION_DST}"
  echo "[FINALIZE] constitution.md snapshot published from .specify/memory/ ✓"
else
  echo "[FINALIZE] ERROR: .specify/memory/constitution.md not found — cannot publish constitution snapshot"
  exit 1
fi

# ── 2. Stage artifacts ────────────────────────────────────────────────────────
git -C "${PROJECT_ROOT}" add "${SPEC_DIR}/"
git -C "${PROJECT_ROOT}" add "${PROJECT_ROOT}/knowledge-base/" 2>/dev/null || true

# ── 3. Commit if anything staged ─────────────────────────────────────────────
if git -C "${PROJECT_ROOT}" diff --cached --quiet; then
  echo "[FINALIZE] Nothing to commit — artifacts already up to date"
else
  git -C "${PROJECT_ROOT}" commit -m \
    "feat(spec): echelon spec run artifacts for ${SPEC_ID}-${FEATURE_NAME} [skip ci]

Squad run complete. Spec, tasks, plan, architecture, and all specialist
outputs committed to feature branch so harness.build can create clean
worktrees.

Run ID: ${RUN_ID}"
  echo "[FINALIZE] Spec artifacts committed ✓"
fi

# ── 4. Push feature branch so harness mirror can resolve it ──────────────────
FEATURE_BRANCH="${SPEC_ID}-${FEATURE_NAME}"
ORIGIN_URL=$(git -C "${PROJECT_ROOT}" remote get-url origin 2>/dev/null || echo "")
IS_LOCAL=0
if [ -z "${ORIGIN_URL}" ]; then
  IS_LOCAL=1
elif echo "${ORIGIN_URL}" | grep -qE '^(/|\./)'; then
  IS_LOCAL=1
elif [ -d "${ORIGIN_URL}" ]; then
  IS_LOCAL=1
fi

if [ "${IS_LOCAL}" -eq 0 ]; then
  # Remote repo — push so the harness mirror can fetch the branch
  if git -C "${PROJECT_ROOT}" push origin "${FEATURE_BRANCH}" --set-upstream 2>/dev/null; then
    echo "[FINALIZE] Feature branch pushed to origin ✓"
  else
    echo "[FINALIZE] WARNING: could not push ${FEATURE_BRANCH} to origin (harness mirror may not see it)"
  fi
else
  echo "[FINALIZE] Local repo — push not needed (mirror clones directly)"
fi

# ── 5. Return to default branch ───────────────────────────────────────────────
DEFAULT_BRANCH="main"
for branch in main master; do
  if git -C "${PROJECT_ROOT}" show-ref --quiet "refs/heads/${branch}"; then
    DEFAULT_BRANCH="${branch}"
    break
  fi
done

CURRENT=$(git -C "${PROJECT_ROOT}" branch --show-current)
if [ "${CURRENT}" = "${DEFAULT_BRANCH}" ]; then
  echo "[FINALIZE] Already on ${DEFAULT_BRANCH} — no checkout needed"
else
  git -C "${PROJECT_ROOT}" checkout "${DEFAULT_BRANCH}"
  echo "[FINALIZE] Switched ${CURRENT} → ${DEFAULT_BRANCH} ✓"
fi

echo "[FINALIZE] Done — feature branch ${FEATURE_BRANCH} ready for harness.run"
