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

## Implementation Progress

The first six ownership foundations are implemented on
`codex/egr-151-spec-lifecycle-gitops`. The sixth slice activates the runtime
cutover after the preceding branch, checkpoint, transaction, and switch
foundations:

- `src/echelon/speckit_git.py` deterministically inspects and verifies
  disablement of spec-kit's project-local Git extension and hooks.
- `src/echelon/phase_a_git.py` derives bounded spec identities, allocates the
  next number across published/run-local directories plus local/remote refs,
  resolves and records the default-branch commit, prepares run-local artifact
  context, and creates a verified sibling branch only from a clean default
  checkout.
- `tests/unit/test_phase_a_git.py` uses temporary real Git repositories and no
  LLM, Docker, or network dependency. It covers explicit and fallback default
  branches, all identity sources, read-only planning, sibling creation, and
  refusal without HEAD movement for staged/tracked/untracked dirt, a non-default
  checkout, a moved default ref, and an existing target branch.
- `src/harness/phase_checkpoints.py` now force-stages only the active spec path,
  excludes runtime checkpoint metadata, preserves unrelated staged, tracked,
  and untracked work, and records the current commit even when the owned path
  has no changes. This remains branch-durable when a workspace broadly ignores
  `/runs/`.
- `src/harness/squad.py` now converts required checkpoint errors into durable
  `phase_checkpoint_failed` terminal blocks at every automatic checkpoint call
  site instead of logging a warning and continuing.
- `src/echelon/cli.py` idempotently maintains the run-local ledger ignore rule
  without overwriting existing `runs/.gitignore` content.
- `src/echelon/spec_lifecycle.py` discovers current and legacy spec runs without
  mtime inference, resolves exact identities before unique numeric prefixes,
  requires `runs/.current` to name an exact run directory, and rejects run or
  artifact paths that escape the project root.
- The same lifecycle module serializes mutations with an owned atomic directory
  lock and journals switch intent before pointer changes. Atomic pointer
  replacement plus explicit recovery handles known pre-checkout, post-checkout,
  and post-pointer crash windows while inconsistent state fails closed.
- `tests/unit/test_spec_lifecycle.py` exercises all lifecycle state transitions
  in temporary filesystems with caller-supplied branch observations. It performs
  no Git checkout, LLM invocation, Docker operation, or network request.
- `src/echelon/spec_switch.py` validates the latest checkpoint owned by each
  exact run, proves commit existence and feature-branch containment, and runs
  existing-run switches under the lifecycle lock. Git checkout precedes the
  active pointer, and an interrupted intent is reconciled before new work.
- Dirty switches now fail with Git-reported paths unless the caller selects a
  managed `--stash` or confirmed `--discard`. Managed stashes persist immutable
  commit SHAs in run state, restore by SHA, drop only after conflict-free apply,
  and remain recorded after conflicts. Discard resets to the validated outgoing
  checkpoint and removes only non-ignored untracked paths.
- `src/echelon/spec_switch_cli.py` and the thin `echelon spec switch
  <spec-or-run-id>` dispatch provide deterministic non-interactive flags and an
  interactive stash/discard/cancel choice. The engine refuses to run unless
  spec-kit Git is already disabled, so this command does not weaken the hard
  ownership dependency while automatic migration remains inactive.
- Focused adjacent verification passed 33 tests on 2026-07-17:
  `test_phase_a_git`, `test_speckit_git`, existing spec switch/resume tests, and
  the RE Git-flow integration test; `git diff --check` also passed.
- The authoritative-checkpoint matrix passed 142 tests on 2026-07-17 across
  checkpoint creation, run metadata, checkpoint CLI routing, rewind, the full
  squad controller integration suite, Phase A Git bootstrap, and spec-kit Git
  ownership; `git diff --check` passed. The broader `test_cli_delivery.py` file
  retains one unrelated pre-existing help assertion that rejects
  `target <spec_id>` as a substring of the already-landed
  `drop-target <spec_id>` command, so the matrix selected its checkpoint-routing
  test explicitly.
- The lifecycle-transaction and adjacent GitOps matrix passed 73 tests on
  2026-07-17 across spec lifecycle state, Phase A Git, authoritative
  checkpoints, existing switch/resume routing, and spec-kit Git inspection.
- The checkpoint-gated switch and adjacent GitOps matrix passed 112 tests on
  2026-07-17. Its temporary real repositories cover clean/idempotent switching,
  checkpoint/branch rejection, checkout recovery, dirty refusal, stash/restore
  and conflict retention, confirmed discard, Git inspection failure, option
  parsing, interactive choices, and CLI dispatch without LLM, Docker, or network
  access.
- `echelon workspace init` now bootstraps workspace Git before idempotently
  disabling and verifying spec-kit Git. A failed or malformed disablement
  blocks initialization, while managed spec run/continue/resume/rewind,
  checkpoint, manual-phase, bugfix, change, and reopen entrypoints fail closed
  if competing spec-kit Git behavior remains.
- `src/echelon/phase_a_start.py` now starts a fresh run under the lifecycle lock.
  It ignores the outgoing workflow status, requires the outgoing run's exact
  checkpoint, applies the same dirty refusal/managed-stash/confirmed-discard
  protocol as switching, creates a sibling branch ref at the recorded default
  commit, writes discoverable prepared run state, checks out the target, and
  updates `runs/.current` only after Git succeeds.
- The squad controller preserves the prepared run/spec/branch/base identity
  when initializing normal workflow state. `SquadCliProvider` snapshots branch
  and HEAD around both primary and control-payload repair invocations and raises
  a lifecycle ownership error if an external agent mutates either.
- New no-LLM real-Git tests cover first and subsequent spec starts, a non-final
  outgoing run, missing checkpoints, sibling ancestry, dirty refusal, managed
  stash, confirmed discard, prepared-state controller handoff, first-run CLI
  directory creation, workspace disablement order/failure, and provider branch
  or commit mutation. The cutover/adjacent matrix passed 221 tests; the three
  full-suite integration fixtures affected by authoritative Git checkpoints
  were migrated to temporary real Git repositories and their focused rerun
  passed 14 tests.
- `echelon spec status` now renders the exact `runs/.current` authoring run,
  declared feature branch, latest validated checkpoint, recorded managed stash,
  and other switchable runs. Invalid checkpoint state remains visible as a
  diagnostic instead of hiding the rest of the orientation report.
- Explicit delivery no longer calls `ensure_on_default_branch()` on the shared
  Phase A checkout. It continues to use the requested spec's readiness gate and
  `.current-build-<spec>` marker, while Git mutations remain within the harness
  mirror and ephemeral worktrees. No-LLM tests prove delivery of spec A preserves
  active spec B's branch, dirty authoring file, and `runs/.current` pointer; a
  separate requested-spec regression proves a ready A cannot authorize unready B.
- `echelon delivery land <spec>` now resolves `runs/.current` before any
  readiness check, branch preparation, merge, cleanup, or status mutation. It
  refuses when another feature branch is active, names both specs and branches,
  and directs the operator to checkpoint/clean then `echelon spec switch` to the
  requested spec. The guard is covered by a temporary real-Git test that proves
  the authoring branch and pointer remain unchanged.

EGR-151 remains `in-progress`. Complete Phase A finalization artifact boundaries,
consider replacing the landing guard with a dedicated landing worktree, add the
changelog entry, and close final full-suite evidence. The full-suite run recorded
3,878 passing tests and seven failures; a focused rerun cleared all three
Git-fixture failures affected by the cutover. Four unrelated existing assertions
remain in CLI help/template contracts outside EGR-151.
