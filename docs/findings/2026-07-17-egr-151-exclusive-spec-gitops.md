# EGR-151 Exclusive Phase A GitOps And Spec Switching

**Review date:** 2026-07-17
**Priority:** P1
**Status:** in-progress
**GitHub:** #164
**Design:** `docs/superpowers/specs/2026-07-17-spec-switch-lifecycle-design.md`

## Summary

Echelon and the spec-kit Git extension can both mutate the same Phase A
checkout. Spec-kit can create and switch feature branches around
`speckit.specify`, while Echelon separately creates checkpoint commits,
finalizes feature branches, updates `runs/.current`, prepares delivery mirrors,
and checks out the default branch. Two Git authorities make it impossible to
guarantee safe multi-spec switching or to run delivery for one spec while
another remains active for authoring.

Echelon must become the sole Git lifecycle authority. Spec-kit remains the
artifact-generation engine, but its Git extension and hooks must be disabled.
This ownership boundary is a hard prerequisite for the remainder of the
accepted spec-switch lifecycle.

## Grounded Evidence

- The installed spec-kit explicitly supports `specify extension disable git`
  and documents that specification continues without branch creation.
- The spec-kit Git extension owns the `before_specify` feature-branch hook and
  optional automatic commit hooks.
- `src/harness/phase_checkpoints.py::create_phase_checkpoint()` currently runs
  `git add -A`, which can commit changes outside the active spec's owned paths.
- `src/harness/squad.py::_checkpoint_successful_phase()` treats checkpoint
  failure as a warning even though safe switching requires a durable checkpoint.
- `src/harness/skills/run_skill.py::run()` calls
  `ensure_on_default_branch()` against the shared authoring checkout before
  delivery creates its mirror worktrees.
- `extension/scripts/bash/finalize-run.sh` commits Phase A artifacts and checks
  out the default branch, while `runs/.current` still represents the Phase A
  authoring selection.
- `extension/workflow/phases/phase4-document.md` still describes branch stacking
  even though the accepted lifecycle requires sibling branches from the default
  branch.

## Required Fix

### 1. Establish exclusive Git ownership

- Add deterministic inspection and verified disablement as the first foundation
  without activating the cutover ahead of Echelon's replacement branch path.
- Implement Echelon-owned default-branch resolution, spec identity allocation,
  sibling-branch creation, and prepared spec-directory context.
- Once checkpoint-gated switching is ready, make `echelon workspace init`
  idempotently disable the spec-kit Git extension.
- Inspect both `.specify/extensions/.registry` and `.specify/extensions.yml` so
  stale or inconsistent enabled Git hooks fail closed.
- Block managed Phase A commands before provider dispatch when competing
  spec-kit Git behavior is enabled or its state is malformed.
- Verify that spec-kit artifact-generation boundaries do not change the branch
  or create commits.
- Activate disablement, fail-closed preflight, and the replacement Git path in
  one tested cutover so first-pass spec creation is never left branchless.

### 2. Make Phase A checkpoints authoritative

- Commit only Echelon-owned paths for the active run/spec.
- Record a checkpoint for the current valid commit even when no new files need
  committing.
- Select checkpoints by run ID and verify branch containment.
- Treat required checkpoint failure as a blocking lifecycle error.

### 3. Add checkpoint-gated spec switching

- Add `echelon spec switch <spec-or-run-id>` with exact, ambiguity-safe run
  resolution.
- Require a valid checkpoint and a clean worktree before checkout.
- Offer managed stash, confirmed discard-to-checkpoint, or cancel for dirty
  worktrees.
- Protect checkout and `runs/.current` updates with a workspace lifecycle lock
  and crash-recoverable switch intent.

### 4. Move new-spec branch creation into Echelon

- Resolve and record the configured default-branch commit.
- Allocate the spec/run identity and create a sibling feature branch from that
  exact commit before invoking `speckit.specify`.
- Reject unexpected branch or commit mutation across the spec-kit boundary.

### 5. Isolate delivery and finalization

- Resolve delivery from the requested run to a validated ready checkpoint or
  finalization commit.
- Create mirror worktrees at that commit without stashing, resetting, or
  checking out the shared Phase A workspace.
- Generate and validate the complete artifact set before the final Phase A
  commit.
- Keep landing separate until it is worktree-isolated or explicitly guarded.

## Acceptance Criteria

- Echelon initialization disables installed spec-kit Git integration and reports
  the resulting ownership state.
- Managed Phase A commands fail before provider creation when spec-kit Git hooks
  are enabled or their state is inconsistent.
- A new spec branch is always a sibling created from the recorded default-branch
  commit by Echelon.
- An unfinished checkpointed run can be selected and resumed explicitly.
- Switching refuses missing checkpoints and unresolved dirty work.
- Stash, discard, cancel, crash recovery, and ambiguous run resolution have
  deterministic real-Git tests.
- Delivery for spec A can run while spec B remains active without changing B's
  branch, dirty state, active-run pointer, or build marker.
- Delivery inputs are pinned to a validated Git commit rather than a mutable
  run-local snapshot.
- The lifecycle integration suite uses temporary Git repositories and scripted
  providers; it requires no LLM, Docker, or network access.
- Completion includes an `[Unreleased]` changelog entry, a fixed EGR register
  row, and recorded focused/full verification evidence.
