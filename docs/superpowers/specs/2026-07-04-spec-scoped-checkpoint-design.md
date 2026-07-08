# Spec-Scoped Checkpoints and Echelon Commit Attribution Design

## Summary

Echelon should use Git-backed checkpoints for Phase A/spec recovery, but checkpoints must be spec-scoped, explicit, and safe around manual edits. Users should discover available recovery points with `echelon spec checkpoint list`, not by guessing phase names or scanning Git history. Every commit created by Echelon, across workspace init, spec work, delivery, recovery, landing, and migrations, must carry machine-parseable attribution trailers so downstream reporting can measure Echelon-authored work.

## Goals

- Create durable Phase A/spec checkpoints after successful phase-node boundaries.
- Make rewind use recorded checkpoint metadata and whole-commit Git branch operations instead of deleting files by hand.
- Scope checkpoint discovery and rewind to the active spec or an explicit `--spec`.
- Preserve user trust by refusing to silently commit manual artifact edits.
- Handle staged/parallel agent phases as one coherent phase checkpoint.
- Add mandatory parseable Echelon attribution to every Echelon-created commit.

## Non-Goals

- Do not scan all Git history to infer checkpoints.
- Do not make raw phase names from `echelon phase list` imply a checkpoint exists.
- Do not auto-commit dirty manual edits as part of normal continuation.
- Do not use path-scoped file restore as the default rewind behavior.

## Current Behavior

Delivery harness checkpointing is already Git-based. Ralph commits dirty worktrees when build progress advances, records entries in `checkpoint_commits`, and recovery prefers checkpoint commits over salvage commits before cherry-picking recovered work into the project checkout.

Phase A/spec rewind is still file-based. `echelon rewind <phase-id>` supports a small set of phase targets, deletes downstream files with filesystem operations, and rewrites run state. This works for narrow recovery cases but does not provide a durable, inspectable checkpoint model.

## Lessons from Delivery Harness Recovery

The delivery harness has already accumulated recovery behavior that Phase A should reuse or intentionally avoid.

Reuse these lessons:

- Prefer explicit state metadata over Git log inference. Delivery recovery first reads `checkpoint_commits` and only falls back to subject-based commit search when metadata is unavailable. Phase A should not need the fallback because spec checkpoints are first-class metadata.
- Validate commit existence before using a recorded SHA. Delivery recovery checks whether recorded checkpoint commits still exist in the source repo before selecting them.
- Treat dirty tracked work as a hard stop. Delivery recovery refuses to apply commits when the project checkout has tracked changes. Phase A rewind should do the same before branch reset.
- Preserve a recoverable source before destructive movement. Delivery recovery uses preserved worktrees and backups for collision cases. Phase A should create a backup ref before moving a branch.
- Distinguish checkpoint, salvage, and final publish commits. Delivery uses checkpoint commits for progress, salvage commits for failure preservation, and publish commits for converged work. Phase A should keep the same conceptual separation: automatic phase checkpoints, explicit user checkpoint commits, and ordinary user commits are different things.
- Avoid empty or metadata-only checkpoints unless intentionally requested. Delivery checkpointing skips when no file changes exist even if progress metadata changed. Phase A should avoid empty phase checkpoint commits.
- Keep recovery idempotent. Delivery recovery returns "already applied" when the target branch already contains the commit. Phase A rewind should similarly detect when the current branch is already at or contains the requested checkpoint and avoid surprising branch movement.
- Test the ugly cases. Delivery has tests for dirty checkouts, missing commits, untracked collisions, empty cherry-picks, preferred checkpoint over salvage, and existing target commits. Phase A needs equivalent tests around dirty worktrees, post-checkpoint commits, missing checkpoint SHAs, wrong spec branch, backup refs, and repeated rewind.

Avoid repeating these issues:

- Do not rely on commit subject heuristics for normal recovery. Delivery still has `_find_strategy_commit()` as a fallback because older state did not always have durable metadata. Phase A should require the spec checkpoint ledger.
- Do not mix artifact recovery with runtime-state recovery. Delivery had to distinguish target repo state, preserved worktree state, and harness state. Phase A should explicitly update ignored/local run state after branch rewind instead of assuming Git restores it.
- Do not silently handle user work except in narrow, proven cases. Delivery has special untracked collision backup logic for cherry-pick recovery. Phase A branch rewind should be simpler: dirty worktree means stop and ask the user to commit, stash, or discard.
- Do not use cherry-pick semantics for rewind. Delivery recovery is applying completed implementation work forward onto a target branch. Phase A rewind is moving a spec branch backward to a known coherent state, so branch reset with a backup ref is the correct primitive.

Reusable code or patterns:

- Use `harness.gitops._run_git` or a public wrapper with the same timeout/error behavior for Git commands.
- Reuse branch-name normalization patterns from delivery recovery.
- Extract shared helpers for commit existence checks, dirty worktree detection, branch containment checks, backup-ref creation, and structured Git errors.
- Reuse the delivery tests as templates, but not the cherry-pick implementation path.

## Checkpoint Model

Phase A checkpoints are spec recovery points. A checkpoint is valid only for the spec that recorded it.

Checkpoint metadata should be spec-scoped and Echelon-owned. The active ledger can live in run state and be mirrored to a spec-scoped file, for example:

```text
specs/<spec-id>/.echelon/checkpoints.json
```

The ledger must not be part of the artifact restore set for the checkpoint it describes. A checkpoint commit cannot record its own final SHA inside a tracked metadata file without creating a self-reference problem. The checkpoint flow should therefore be:

1. Commit changed spec artifacts and required project files.
2. Read the resulting commit SHA.
3. Record that SHA in run state and the spec-scoped checkpoint ledger.
4. If the ledger is tracked, commit the ledger update separately as checkpoint metadata.

Rewind moves the active spec branch back to the recorded artifact commit, not to the later metadata commit. `echelon spec checkpoint list` reads the latest ledger from active run state or the spec-scoped ledger for the selected spec.

Each entry records:

```json
{
  "id": "phase3-plan",
  "spec_id": "001-demo",
  "phase": "phase3-plan",
  "next_phase": "phase3-consensus",
  "commit": "abc123...",
  "metadata_commit": "def456...",
  "artifact_paths": [
    "specs/001-demo/spec.md",
    "specs/001-demo/plan.md",
    "specs/001-demo/tasks.md"
  ],
  "source": "auto",
  "run_id": "squad-20260704-123456",
  "created_at": "2026-07-04T12:34:56Z"
}
```

`source` values:

- `auto`: Echelon created the checkpoint after a successful phase-node.
- `user-accepted`: user explicitly accepted an already committed baseline.
- `user-committed`: user used an Echelon command to commit manual edits with Echelon trailers.

## Phase Boundary Rules

Automatic checkpointing happens only after a successful phase-node boundary:

- The executor has returned success.
- Published artifacts are coherent.
- `SquadStateStore.advance()` has completed or the checkpoint service receives the post-advance state.
- The workspace has no unattributed dirty changes in checkpoint-relevant paths.
- The checkpoint commit would be non-empty.

Parallel or staged agents must not checkpoint mid-execution. A staged/parallel phase produces one checkpoint for the whole phase-node after all participating agents finish and artifacts are published.

Manual phase replay follows the same rule: if `echelon phase run <phase-id>` succeeds and publishes artifacts, it may create a checkpoint for that phase-node under the same dirty-worktree constraints.

## Manual Edit Handling

Manual edits to `spec.md`, `tasks.md`, `plan.md`, or related spec artifacts must not be silently folded into the next automatic checkpoint.

If Echelon detects dirty checkpoint-relevant files before continuing, checkpointing, or rewinding, it should stop with actionable guidance:

```text
Manual artifact edits detected for spec 001-demo:
  specs/001-demo/spec.md
  specs/001-demo/tasks.md

These edits are not part of an Echelon checkpoint.

Options:
  echelon spec checkpoint commit --spec 001 --message "refine tasks after review"
  echelon spec checkpoint accept --spec 001
  git commit ...
```

`echelon spec checkpoint accept` should not commit dirty files. It records the current `HEAD` as a user-accepted checkpoint only when the relevant artifacts are already clean and committed.

`echelon spec checkpoint commit --message ...` is the explicit command that commits manual edits with required Echelon attribution trailers. This lets users intentionally move the checkpoint baseline without Echelon guessing.

Raw `git commit` remains allowed, but Echelon should classify it as a user-authored baseline unless the required Echelon trailers are present.

## User-Facing Commands

`echelon phase list` remains the workflow catalog. It answers: which phases exist?

`echelon spec checkpoint list` is the recovery catalog. It answers: which recovery points exist for this spec?

Commands:

```text
echelon spec checkpoint list
echelon spec checkpoint list --spec 001
echelon spec checkpoint show <checkpoint-id>
echelon spec checkpoint accept --spec 001
echelon spec checkpoint commit --spec 001 --message "<message>"
echelon spec rewind <phase-id>
echelon spec rewind --to checkpoint:<checkpoint-id>
```

Example output:

```text
CHECKPOINTS - spec 001-demo

ID                       PHASE                 COMMIT      SOURCE
phase1-constitution      phase1-constitution   a1b2c3d     auto
phase1-what              phase1-what           b4c5d6e     auto
phase3-how               phase3-how            c7d8e9f     auto
phase3-plan              phase3-plan           d0e1f2a     auto
manual-review-20260704   phase3-plan           e3f4a5b     user-committed

Current phase: phase3-consensus
Rewind with:   echelon rewind phase3-plan
```

If no active spec can be resolved:

```text
No active spec resolved.

Use:
  echelon spec checkpoint list --spec 001
```

If the checkpoint belongs to a different spec:

```text
Checkpoint phase3-plan belongs to spec 001-demo, but active spec is 002-api-auth.
```

## Rewind Behavior

Rewind resolves targets through spec-scoped checkpoint metadata. It must not scan Git history with subject or grep heuristics.

The default rewind operation should restore the whole checkpoint commit state on the active spec branch. Path-scoped restore is not safe as the normal behavior because Phase A artifacts are semantically coupled and file lists can miss renames, deletes, generated metadata, or newly introduced artifact paths.

Default rewind flow:

1. Resolve active spec from current run state, or require `--spec`.
2. Load spec checkpoint metadata.
3. Resolve `<phase-id>` or `checkpoint:<id>` to a checkpoint entry for that spec.
4. Verify the current branch is the spec branch for that spec.
5. Refuse if the worktree has uncommitted changes unless the user explicitly commits, stashes, or discards them.
6. If commits exist after the checkpoint, show them and require explicit confirmation.
7. Create a safety ref before moving the branch.
8. Move the spec branch to the checkpoint commit.
9. Update runtime state to resume at the requested phase.
10. Record a rewind audit entry in state and checkpoint metadata.

Default rewind should be branch-level:

```bash
git branch echelon/backup/<spec-id>-before-rewind-<timestamp> HEAD
git reset --hard <checkpoint-commit>
```

The command should show the exact branch movement before changing anything:

```text
Rewind will move branch 001-demo:
  from: f9e8d7c current HEAD
  to:   d0e1f2a phase3-plan checkpoint

Backup branch:
  echelon/backup/001-demo-before-rewind-20260704-123456

Continue with:
  echelon rewind phase3-plan --confirm
```

Detached checkout is useful for inspection but should not be the default continuation path. It can be exposed separately as `echelon checkpoint inspect <checkpoint-id>` or a dry-run mode.

Path-scoped restore may exist only as an advanced salvage operation, for example `echelon checkpoint restore-files <checkpoint-id>`, and should be documented as manual recovery rather than normal rewind.

Runtime state should be handled separately from project artifacts. If run state is ignored/local, Echelon should update it deterministically after the branch rewind rather than relying on Git to restore runtime files.

## Commit Attribution Contract

Every commit created by Echelon must include a standard `Co-authored-by` trailer and stable `Echelon-*` trailers.

Minimum required trailer:

```text
Co-authored-by: Echelon <echelon@b3cognition.dev>
```

Common structured trailers:

```text
Echelon-Origin: phase-a
Echelon-Action: checkpoint
Echelon-Spec: 001-demo
Echelon-Run: squad-20260704-123456
Echelon-Phase: phase3-plan
```

Delivery example:

```text
Co-authored-by: Echelon <echelon@b3cognition.dev>
Echelon-Origin: delivery
Echelon-Action: implementation
Echelon-Spec: 001-demo
Echelon-Strategy: default
Echelon-Run: build-20260704-123456
```

Workspace init example:

```text
Co-authored-by: Echelon <echelon@b3cognition.dev>
Echelon-Origin: workspace
Echelon-Action: init
```

Manual checkpoint commit example:

```text
Co-authored-by: Echelon <echelon@b3cognition.dev>
Echelon-Origin: phase-a
Echelon-Action: user-committed-checkpoint
Echelon-Spec: 001-demo
Echelon-Run: squad-20260704-123456
Echelon-Phase: phase3-plan
```

Rules:

- All Echelon commit creation paths must use one commit-message builder.
- Subjects remain human-readable, but parsing must rely on trailers.
- Direct ad hoc commit messages in Echelon code should be removed.
- Raw user commits without trailers are not counted as Echelon-authored work.
- User-accepted checkpoint baselines should be tracked as accepted baselines, not Echelon-authored commits, unless Echelon created the commit.

## Architecture

Add a small checkpoint subsystem rather than expanding `src/echelon/cli.py`.

Suggested modules:

- `src/echelon/commit_messages.py`
  Builds commit messages with required Echelon trailers.

- `src/harness/phase_checkpoints.py`
  Reads and writes spec-scoped checkpoint metadata, resolves active spec checkpoints, detects dirty relevant paths, and creates phase checkpoint commits.

- `src/echelon/checkpoint_cli.py`
  Implements `echelon spec checkpoint list/show/accept/commit`.

- `src/echelon/rewind.py`
  Moves rewind logic out of `cli.py`, validates spec branch state, creates backup refs, and moves the branch to recorded checkpoint commits.

Existing delivery code should migrate to the shared commit-message builder while preserving current checkpoint recovery behavior.

## Error Handling

- Missing active spec: require `--spec`.
- Missing checkpoint metadata: tell the user no checkpoints exist for that spec and suggest `echelon phase list`.
- Dirty checkpoint-relevant paths: refuse automatic checkpoint/rewind and show accept/commit/manual options.
- Checkpoint commit missing from local Git object database: report the exact missing SHA and suggest fetching the branch or rerunning the phase.
- Checkpoint/spec mismatch: refuse.
- Dirty worktree: refuse before moving the branch unless the user explicitly commits, stashes, or discards local edits.
- Post-checkpoint commits: show the commits that will be moved behind the backup ref and require explicit confirmation.
- Secret scan failure: block the commit and do not record checkpoint metadata.

## Testing

Add focused unit tests for:

- Phase checkpoint creation after a successful normal phase-node.
- One checkpoint for staged/parallel phase completion, none during partial execution.
- No checkpoint when relevant files are dirty from manual edits.
- `checkpoint list` reads only spec metadata and does not scan Git history.
- Checkpoint metadata records the artifact commit after creation and avoids self-referential commits.
- `rewind phase3-plan` resolves through metadata, creates a backup ref, and moves the spec branch to the checkpoint commit.
- Rewind refuses dirty worktrees and requires confirmation when commits exist after the checkpoint.
- Rewind refuses checkpoints from another spec.
- `checkpoint accept` records clean committed `HEAD` and refuses dirty files.
- `checkpoint commit` creates trailers.
- All Echelon commit-producing paths include `Co-authored-by` and `Echelon-*` trailers.

Regression tests should cover existing delivery checkpoint behavior so the new commit-message builder does not break harness recovery.
