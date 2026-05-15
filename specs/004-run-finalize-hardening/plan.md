# Run Finalize Hardening — Implementation Plan

## Overview

Four targeted changes. The core is a new `finalize-run.sh` script that makes the spec commit + branch-switch deterministic. The other three changes wire it in and add resilience for the constitution.md gap.

---

## Tasks

### T-001 — Create `finalize-run.sh`

**File:** `extension/scripts/bash/finalize-run.sh` (new)

**What it does:**
1. Reads args: `PROJECT_ROOT`, `SPEC_ID`, `FEATURE_NAME`, `RUN_ID`
2. Derives `SPEC_DIR="${PROJECT_ROOT}/specs/${SPEC_ID}-${FEATURE_NAME}"`
3. Copies `.specify/memory/constitution.md` → `${SPEC_DIR}/constitution.md` (warn + continue if source missing)
4. `git add "${SPEC_DIR}/"` + `git add "${PROJECT_ROOT}/knowledge-base/"` (suppress error if missing)
5. If staged changes: commits with template message; otherwise logs "nothing to commit"
6. Detects default branch (`main` → `master` fallback via `git show-ref`)
7. If not already on default branch: `git checkout ${DEFAULT_BRANCH}`

```bash
#!/usr/bin/env bash
# finalize-run.sh — Commit spec artifacts to feature branch and return to default branch.
# Called as the terminal step of echelon run (phase4-document §12.10b+12.11).
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
  cp "${CONSTITUTION_SRC}" "${CONSTITUTION_DST}"
  echo "[FINALIZE] constitution.md copied from .specify/memory/ ✓"
else
  echo "[FINALIZE] WARNING: .specify/memory/constitution.md not found — skipping copy"
fi

# ── 2. Stage artifacts ────────────────────────────────────────────────────────
git -C "${PROJECT_ROOT}" add "${SPEC_DIR}/"
git -C "${PROJECT_ROOT}" add "${PROJECT_ROOT}/knowledge-base/" 2>/dev/null || true

# ── 3. Commit if anything staged ─────────────────────────────────────────────
if git -C "${PROJECT_ROOT}" diff --cached --quiet; then
  echo "[FINALIZE] Nothing to commit — artifacts already up to date"
else
  git -C "${PROJECT_ROOT}" commit -m \
    "feat(spec): echelon run artifacts for ${SPEC_ID}-${FEATURE_NAME} [skip ci]

Squad run complete. Spec, tasks, plan, architecture, and all specialist
outputs committed to feature branch so harness.build can create clean
worktrees.

Run ID: ${RUN_ID}"
  echo "[FINALIZE] Spec artifacts committed ✓"
fi

# ── 4. Return to default branch ───────────────────────────────────────────────
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

echo "[FINALIZE] Done — feature branch ${SPEC_ID}-${FEATURE_NAME} ready for harness.run"
```

**Acceptance:** Script exits 0 in all cases (nothing to commit, already on default branch, missing constitution source). Exits non-zero only on real git failures.

**Dependencies:** None.

---

### T-002 — Replace §12.10b + §12.11 in `phase4-document.md`

**File:** `extension/workflow/phases/phase4-document.md`

**Change:** Collapse the current §12.10b and §12.11 into a single step that calls `finalize-run.sh` via the Bash tool. COMMANDER reads `RUN_ID` from `state.json`, then executes:

Replace the content of **§12.10b** with:

```markdown
### 12.10b Commit Spec Artifacts and Return to Default Branch — MANDATORY

**This step MUST be executed as a Bash tool call — no inline git operations, no prose substitution.**

Read `RUN_ID` from state.json:

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.specify/squad/state.json')).get('run_id','unknown'))" 2>/dev/null || echo "unknown")
```

Then call `finalize-run.sh`:

```bash
bash "${PROJECT_ROOT}/.specify/extensions/echelon/scripts/bash/finalize-run.sh" \
  "${PROJECT_ROOT}" "${SPEC_ID}" "${FEATURE_NAME}" "${RUN_ID}"
```

If exit code is non-zero, report the error and stop. Do not proceed to §12.12.

This single script: copies constitution.md from `.specify/memory/` into the spec dir, commits all spec artifacts to the feature branch with a structured message, and switches the working directory back to the default branch.
```

**Remove §12.11 entirely** (its content is now inside `finalize-run.sh`). Renumber §12.12 → §12.11.

**Acceptance:** COMMANDER has no inline git commands to execute — one Bash tool call only.

**Dependencies:** T-001.

---

### T-003 — Constitution fallback in `codegen-A-preamble.md §A.2`

**File:** `extension/workflow/phases/codegen-A-preamble.md`

**Change:** In §A.2, after the missing-artifact check but before the hard-stop, insert a constitution-specific recovery step:

```bash
# If constitution.md is missing from spec dir, attempt recovery from .specify/memory/
if echo "${MISSING}" | grep -q "constitution.md"; then
  if [ -f "${PROJECT_ROOT}/.specify/memory/constitution.md" ]; then
    cp "${PROJECT_ROOT}/.specify/memory/constitution.md" \
       "${FEATURE_DIR}/constitution.md"
    echo "[RECOVERY] constitution.md copied from .specify/memory/ ✓"
    MISSING=$(echo "${MISSING}" | sed 's/ constitution\.md//')
  fi
fi
if [ -n "${MISSING}" ]; then
  echo "[ECHELON CODEGEN] ERROR: Missing Phase A artifacts:${MISSING}"
  echo "[ECHELON CODEGEN] Run speckit.echelon.run ${FEATURE_PATH} first."
  exit 1
fi
```

The logic: attempt recovery for constitution specifically, then re-evaluate whether any other files are still missing before deciding to hard-stop.

**Acceptance:** AC-2.1 and AC-2.2 from spec.

**Dependencies:** T-001 (conceptually; this is independent code).

---

### T-004 — Constitution fallback in `build-1-init.md §1.1`

**File:** `extension/workflow/phases/build-1-init.md`

**Change:** After the existing `tasks.md` / `spec.md` hard-stop check in §1.1, add a pre-check that resolves `constitution.md` before the main validation loop runs:

```bash
# Resolve constitution.md — copy from .specify/memory/ if missing from spec dir
if [ ! -f "${SPEC_DIR}/constitution.md" ]; then
  if [ -f "${PROJECT_ROOT}/.specify/memory/constitution.md" ]; then
    cp "${PROJECT_ROOT}/.specify/memory/constitution.md" \
       "${SPEC_DIR}/constitution.md"
    echo "[RECOVERY] constitution.md copied from .specify/memory/ ✓"
  fi
fi
```

This runs before any artifact enumeration, so the subsequent checks see the file as present.

**Acceptance:** AC-2.3 from spec.

**Dependencies:** T-001 (conceptually; this is independent code).

---

## Change Summary

| File | Change type | Risk |
|------|-------------|------|
| `extension/scripts/bash/finalize-run.sh` | New script | Low — additive |
| `extension/workflow/phases/phase4-document.md` | §12.10b rewrite + §12.11 removal | Low — deterministic replacement |
| `extension/workflow/phases/codegen-A-preamble.md` | §A.2 resilience insert | Low — recovery before existing hard-stop |
| `extension/workflow/phases/build-1-init.md` | §1.1 resilience insert | Low — pre-check before existing validation |

**Total: 1 new file + 3 targeted edits.**
