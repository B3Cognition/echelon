# Spec Switch Lifecycle Design

**Status:** Approved
**Date:** 2026-07-17
**Deciders:** Echelon maintainers

## Purpose

Allow multiple Phase A specification runs to coexist in one Echelon workspace.
One run is active for implicit authoring commands, while every run remains
durable, checkpointed, branch-scoped, and explicitly resumable. Delivery for a
named spec must remain independent of the active authoring run.

This lifecycle must be testable with temporary Git repositories and scripted
providers. No LLM invocation is required.

## Invariants

1. A new spec may start regardless of the previous spec's workflow status.
2. Every new spec branch starts from the configured default branch, normally
   `main`; spec branches are siblings, not stacked branches.
3. Leaving an existing spec requires a valid Phase A checkpoint.
4. A branch switch occurs only from a clean worktree. Dirty work must first be
   stashed, discarded back to the checkpoint, or left untouched by cancelling.
5. `runs/.current` identifies only the active Phase A authoring run.
6. Explicitly addressed delivery state remains spec-scoped and does not read or
   modify `runs/.current`.
7. `echelon delivery run <spec>` never stashes, resets, or checks out the shared
   Phase A workspace.
8. Phase A readiness does not merge a feature branch into the default branch.
   Merge remains a delivery/landing operation.

## Options Considered

### Option A: Require a clean worktree and leave Git recovery to the user

This is simple but makes normal interrupted work awkward and leaves stash
identity, checkpoint selection, and branch restoration as manual procedures.

### Option B: Checkpoint-gated switching with managed stash/discard

This reuses the existing Phase A checkpoint ledger. Echelon validates the
checkpoint, offers safe dirty-worktree actions, switches the branch, and changes
the active-run pointer only after Git succeeds.

This is the chosen approach. It provides safe switching without introducing a
second worktree architecture for Phase A.

### Option C: One Git worktree per Phase A spec

This provides the strongest physical isolation, but current agents and phase
contracts assume one project root. Adopting it would require a broader dual-root
refactor across spec-kit, context assembly, publication, and shared knowledge
artifacts. It is not required for this lifecycle.

## Active Spec Model

`runs/.current` is the sole active-authoring pointer. It contains a run-directory
name, never a branch name or spec prefix. Commands that omit a spec reference use
that run:

- `echelon spec continue`
- `echelon spec resume`
- `echelon spec rewind`
- `echelon spec status`
- `echelon phase run <phase>` without `--spec`

Each run's `state.json` supplies `run_id`, `spec_id`, `spec_dir`,
`published_spec_dir`, and `feature_branch`. Explicit resolution accepts:

1. an exact run-directory name;
2. an exact `run_id`;
3. an exact `spec_id` or feature-branch name;
4. a unique numeric spec prefix such as `001`.

Ambiguous prefixes fail and list the matching runs. Resolution scans only
well-formed run directories with readable state; modification time is never used
to guess among matches.

`echelon spec status` shows the active run, active branch, latest checkpoint,
recorded stash state, and the other switchable runs.

## Switch Command

```text
echelon spec switch <spec-or-run-id> [--stash | --discard --confirm]
                    [--restore-stash]
```

The command is deterministic Python and invokes no provider.

### Outgoing Validation

Before leaving the active run, Echelon:

1. resolves its run-local spec directory;
2. loads its Phase A checkpoint ledger;
3. selects the latest checkpoint for that run;
4. verifies that the checkpoint commit exists;
5. verifies that the outgoing feature branch contains that commit;
6. verifies that the current Git branch is the outgoing feature branch; and
7. inspects tracked, staged, and untracked worktree changes.

A clean run without a valid checkpoint cannot be left. A status such as
`running`, `blocked`, or `done` does not independently allow or prohibit the
switch.

### Target Validation

The target run must have a valid checkpoint and an existing feature branch. Its
checkpoint commit must exist on that branch. Switching to the already-active run
is an idempotent success after validating that the pointer and branch agree.

Starting a brand-new spec is the only target-side exception because the new run
has no branch or checkpoint yet. The outgoing run still must pass all switch
safety checks before Echelon checks out the default branch and allocates the new
run.

### Clean Switch

For a clean worktree:

1. checkout the target feature branch, or the default branch for a new spec;
2. verify the resulting branch name;
3. atomically replace `runs/.current` for an existing target, or create the new
   run and then write its pointer; and
4. print the selected run, branch, checkpoint, and next command.

If checkout fails, the active-run pointer remains unchanged.

## Dirty Worktree Handling

When a valid outgoing checkpoint exists but the worktree is dirty, an
interactive command offers:

```text
[s] Stash changes and switch
[d] Discard changes back to the checkpoint
[c] Cancel
```

The default is cancel. In non-interactive execution, dirty work fails unless an
explicit action flag is present.

### Stash

Stashing uses `git stash push --include-untracked` with a message containing the
outgoing run ID, spec ID, and branch. Echelon resolves and records the resulting
stash commit ID in the outgoing run state; it never stores `stash@{N}` as durable
identity.

After the stash succeeds, Echelon verifies that the worktree is clean before
checking out the target. A stash failure leaves the branch and active pointer
unchanged.

When returning to a run with a recorded stash, interactive mode offers to
restore it. `--restore-stash` requests the same behavior non-interactively.
Restoration uses the recorded commit ID, applies rather than pops, and drops the
stash only after a conflict-free apply. A conflict keeps the stash record and
reports normal Git conflict recovery commands.

### Discard

Discard is destructive and requires an interactive confirmation or both
`--discard` and `--confirm`. It:

1. resets tracked and staged files to the latest validated checkpoint commit;
2. removes Git-reported untracked files and directories, but never ignored
   paths; and
3. verifies the worktree is clean before switching.

No backup branch is implied because the user explicitly chose checkpoint-only
recovery. The command prints the checkpoint ID and commit before confirmation.

## Starting A New Spec

`echelon spec run "<description>"` uses the same outgoing-run safety protocol
when another Phase A run is active:

1. require a valid outgoing checkpoint;
2. resolve dirty work through stash, discard, or cancel;
3. checkout and verify the configured default branch;
4. allocate a new run directory and make it active; and
5. let the normal WHAT/spec-kit flow create a new sibling feature branch.

The new branch must be based on the verified default-branch commit. A branch
created from the outgoing feature branch is a lifecycle error and blocks the run.

## Delivery Isolation

Delivery is explicitly spec-addressed:

```text
echelon delivery run 001-spec-a
```

It resolves spec A from durable run state and run-local Phase A artifacts, not
from `runs/.current` and not by assuming spec A is visible in the current
checkout. Its build marker remains spec-scoped:

```text
runs/.current-build-001-spec-a
```

Delivery finds spec A's feature branch in the mirror and creates a worktree on
that branch. It may run while spec B remains the active authoring run and branch.
Delivery must not call `ensure_on_default_branch()` for the shared workspace,
stash spec B, checkout another branch there, or update the Phase A pointer.

Delivery readiness is evaluated for the requested run-local spec snapshot. An
incomplete requested spec blocks before provider dispatch even if another spec
is ready. A ready requested spec proceeds even if the active authoring spec is
incomplete.

`echelon delivery land` remains separate because the current implementation can
mutate the shared checkout while preparing and merging branches. Until landing
is worktree-isolated, it must refuse to disturb a different active Phase A
branch and provide explicit switch/cleanup guidance.

## Failure And Recovery Rules

- Missing, malformed, unreachable, or branch-mismatched checkpoints block the
  switch without changing Git or `runs/.current`.
- Missing target branches block without changing the active run.
- Detached HEAD blocks switching.
- Unrelated dirty source changes are treated exactly like other dirty changes;
  Echelon never silently commits them.
- Stash, reset, cleanup, checkout, and pointer-write errors are reported with
  the last verified branch and pointer state.
- Pointer replacement is atomic. Git checkout always precedes pointer mutation.
- A process interruption after checkout but before pointer replacement is
  detected on the next command by comparing the branch with the active run.
  Status reports the mismatch and offers a deterministic repair.

## Test Strategy

All lifecycle tests run without an LLM. They use temporary real Git repositories
for branch, commit, stash, reset, mirror, and worktree behavior. Scripted fake
providers are used only when a controller boundary must be crossed; readiness
failures assert that no provider is invoked.

### Unit Coverage

- exact and prefix run resolution, including ambiguity;
- checkpoint selection and commit/branch validation;
- active pointer atomic replacement and rollback on checkout failure;
- dirty-worktree action parsing and non-interactive refusal;
- stash commit recording, conflict retention, and successful restoration;
- discard confirmation and checkpoint reset;
- delivery resolution independent of `runs/.current`; and
- requested-spec readiness validation.

### Real-Git Integration Flow

1. Create `main` and spec A's run and feature branch.
2. Advance spec A to a real Phase A checkpoint but leave it non-terminal.
3. Verify that starting spec B is allowed only through the checkpoint/cleanliness
   protocol and that B branches from `main`, not A.
4. Verify branches A and B both exist and have independent ancestry.
5. Switch A -> B -> A by spec ID and run ID, checking the branch and
   `runs/.current` after every operation.
6. Repeat with dirty A using stash, stash restoration, discard, and cancel.
7. Attempt delivery for incomplete A and B; assert failure before provider
   dispatch.
8. Mark A ready, keep B active and incomplete, and start delivery A.
9. Assert the shared checkout remains on B, `runs/.current` still names B,
   delivery uses an A worktree, and only A's build marker changes.
10. Mark B ready and repeat delivery isolation in the opposite direction.

The integration test asserts repository state rather than mocked Git calls. It
therefore covers the complete lifecycle contract while remaining deterministic
and independent of an LLM, Docker, or network access.

## Documentation Corrections

Workflow documentation that describes new specs as branch-stacked must be
updated. The supported model is sibling feature branches from the configured
default branch. Command help and README examples must distinguish the active
Phase A spec from explicitly addressed delivery state.
