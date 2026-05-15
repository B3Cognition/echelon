# Run Finalize Hardening — Specification

> Make the terminal steps of `echelon run` (commit spec artifacts + return to main) deterministic infrastructure operations rather than LLM-orchestrated instructions that can be skipped under context pressure. Simultaneously fix the constitution.md handoff gap that prevents `echelon.build` and `echelon.codegen` from finding it in the spec directory.

**Status**: Draft

---

## Background

`echelon run` ends with two critical handoff steps currently written as LLM instructions in `phase4-document.md`:

- **§12.10b** — commit all spec artifacts to the feature branch (so harness worktrees see them)
- **§12.11** — `git checkout main` (so harness can create worktrees without "branch already checked out" conflict)

Both were skipped in practice. The harness recovers from the branch issue via auto-stash, but if §12.10b is skipped or incomplete, uncommitted artifacts get stashed and become invisible to worktrees. Additionally, §12.10b never copies `.specify/memory/constitution.md` into the spec directory, so `codegen-A-preamble §A.2` and `build-1-init §1.1` always fail to find it.

---

## User Scenarios & Testing

### Scenario 1: Clean finalization after echelon run

**As a** developer who just completed `echelon run`,
**I want** the spec artifacts automatically committed to the feature branch and the repo returned to main,
**So that** `echelon harness run` starts cleanly without stash recovery or missing-artifact errors.

#### Acceptance Criteria

- **AC-1.1:** Given a completed `echelon run`, when §12.10b executes, then `finalize-run.sh` is called via Bash tool and exits 0, committing all artifacts in `${SPEC_DIR}/` plus `constitution.md` to the feature branch.
- **AC-1.2:** Given `finalize-run.sh` runs, when there are no staged changes (re-run case), then the script skips the commit and exits 0 without error.
- **AC-1.3:** Given `finalize-run.sh` runs, when it completes, then the working directory is on the default branch (`main` or `master`).
- **AC-1.4:** Given `finalize-run.sh` runs, when `.specify/memory/constitution.md` exists, then it is copied to `${SPEC_DIR}/constitution.md` before staging, so it is included in the commit.
- **AC-1.5:** Given `finalize-run.sh` runs, when `.specify/memory/constitution.md` does not exist, then the script logs a warning and proceeds — no hard stop.

### Scenario 2: Harness resilience when constitution.md was not committed

**As a** developer running `echelon harness run` against a spec created before this fix,
**I want** the harness to recover gracefully if `constitution.md` is missing from the spec dir but present in `.specify/memory/`,
**So that** I don't get a hard-stop on a fixable condition.

#### Acceptance Criteria

- **AC-2.1:** Given `specs/{NNN}-{feature}/constitution.md` is missing and `.specify/memory/constitution.md` exists, when `codegen-A-preamble §A.2` runs its artifact validation, then it copies constitution.md from `.specify/memory/` into the spec dir, logs the recovery, and continues.
- **AC-2.2:** Given `specs/{NNN}-{feature}/constitution.md` is missing and `.specify/memory/constitution.md` also does not exist, when `codegen-A-preamble §A.2` validates artifacts, then it hard-stops with a clear error naming both paths checked.
- **AC-2.3:** Given the same two conditions (AC-2.1 and AC-2.2), when `build-1-init §1.1` validates artifacts, then it behaves identically to `codegen-A-preamble §A.2`.

### Scenario 3: Commit message follows template

**As a** developer reviewing git history,
**I want** the finalize commit to have a structured, informative message,
**So that** the spec handoff is clearly identifiable in git log.

#### Acceptance Criteria

- **AC-3.1:** Given `finalize-run.sh` commits, then the commit message follows the format: `feat(spec): echelon run artifacts for {SPEC_ID}-{FEATURE_NAME} [skip ci]` with a body containing run ID and a brief description.

---

## Functional Requirements

### finalize-run.sh script

- **FR-001**: A new script `extension/scripts/bash/finalize-run.sh` MUST be created. It accepts four positional arguments: `PROJECT_ROOT`, `SPEC_ID`, `FEATURE_NAME`, `RUN_ID`.
- **FR-002**: `finalize-run.sh` MUST copy `.specify/memory/constitution.md` into `${SPEC_DIR}/constitution.md` if the source exists. If the source does not exist, it MUST log a warning and continue.
- **FR-003**: `finalize-run.sh` MUST stage `${SPEC_DIR}/` and `knowledge-base/` (if it exists) using `git add`.
- **FR-004**: `finalize-run.sh` MUST commit only if there are staged changes (`git diff --cached --quiet` exits non-zero). If nothing is staged, it MUST skip the commit and log this.
- **FR-005**: `finalize-run.sh` MUST use the commit message template: `feat(spec): echelon run artifacts for {SPEC_ID}-{FEATURE_NAME} [skip ci]` with a body line `Run ID: {RUN_ID}`.
- **FR-006**: `finalize-run.sh` MUST switch to the default branch (`main`, falling back to `master`) after committing, using `git checkout`. If already on the default branch, it MUST skip the checkout and log this.
- **FR-007**: `finalize-run.sh` MUST be executable (`chmod +x`) and use `#!/usr/bin/env bash` with `set -euo pipefail`.

### phase4-document.md

- **FR-008**: `phase4-document.md §12.10b` and `§12.11` MUST be collapsed into a single step that calls `finalize-run.sh` via the Bash tool. COMMANDER MUST NOT implement the git operations inline — the script is the only permitted path.
- **FR-009**: The step MUST pass `PROJECT_ROOT`, `SPEC_ID`, `FEATURE_NAME`, and `RUN_ID` (read from `state.json`) as arguments to `finalize-run.sh`.

### Harness resilience (constitution fallback)

- **FR-010**: `codegen-A-preamble.md §A.2` artifact validation MUST attempt to copy `.specify/memory/constitution.md` to the spec dir before declaring constitution.md missing.
- **FR-011**: `build-1-init.md §1.1` artifact validation MUST apply the same fallback as FR-010.
- **FR-012**: Both fallback paths MUST log a single informational line when the copy is performed (e.g. `[RECOVERY] constitution.md copied from .specify/memory/`).

---

## Non-Functional Requirements

| ID | Category | Requirement | Measurable Target |
|----|----------|-------------|-------------------|
| NFR-001 | Determinism | Commit and branch-switch are Bash operations, not LLM text generation | Zero LLM reasoning in §12.10b+12.11 execution path |
| NFR-002 | Idempotency | Running `finalize-run.sh` twice produces no error and no duplicate commit | `git diff --cached --quiet` guard |
| NFR-003 | Backward compat | Existing runs that already committed constitution.md are unaffected | Copy is skipped if dest already exists and is identical |
| NFR-004 | Scope | No other phases or agents modified | Exactly 4 files changed |

---

## Scope

### In Scope (MVP)
- `extension/scripts/bash/finalize-run.sh` — new script (copy constitution + commit + checkout)
- `extension/workflow/phases/phase4-document.md` — §12.10b+§12.11 replaced with single `finalize-run.sh` call
- `extension/workflow/phases/codegen-A-preamble.md` — constitution fallback in §A.2
- `extension/workflow/phases/build-1-init.md` — constitution fallback in §1.1

### Explicitly Out of Scope
- Changing where `speckit.constitution` writes the file (`.specify/memory/` is spec-kit's domain)
- Harness python code changes
- Any other phase or agent
