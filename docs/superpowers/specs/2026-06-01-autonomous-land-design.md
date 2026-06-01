# Autonomous `echelon land` Design

## Purpose

`echelon land <spec_id>` should be the normal final step after `echelon run`,
`echelon harness run`, `echelon resume`, or `echelon continue` converges. It
should land completed feature-branch work with as much autonomy as is safe,
while preserving human control for semantic conflicts.

The target user experience is:

```bash
echelon run "<feature>"
echelon continue
echelon harness run <spec_id>
echelon harness resume <spec_id>
echelon land <spec_id>
```

When auto-land is enabled after a converged harness run, it should use the same
landing machinery. Auto-land may prepare and push the feature branch, but it
must not leave `main` dirty or half-merged.

## Current Problem

The current `land()` implementation has two paths:

1. If a PR URL exists, ask `gh` or `glab` to merge it.
2. If no PR URL exists, merge the feature branch directly into the default
   branch.

When direct merge fails, the command can leave the local repository in a merge
state and only prints generic guidance. It also does not help with common,
low-risk preparation tasks such as merging `main` into the feature branch,
resolving `.gitignore` add/add conflicts, dropping ignored runtime files, and
pushing the prepared branch.

## Design Principles

- Prefer PR-based landing when available.
- Prefer merge over rebase by default for feature-branch preparation, because
  merge is non-destructive and can be pushed without force.
- Never force-push by default.
- Never auto-resolve semantic source/spec conflicts unless a deterministic
  resolver exists for that file type.
- Keep failed landing attempts on the feature branch, not on `main`.
- Leave the repository clean after failed direct landing attempts whenever no
  conflict-resolution session is intentionally in progress.
- Print every automatic resolution that was applied.
- Make `echelon land <spec_id>` idempotent: rerunning it should either continue
  an in-progress landing, finish cleanup, or print the next exact action.

## Command Model

### Default

```bash
echelon land <spec_id>
```

Autonomous default. It may:

- inspect branch and PR state
- prepare the feature branch with a merge from default branch
- auto-resolve low-risk hygiene conflicts
- verify
- push the feature branch
- retry PR/direct landing

It must stop for semantic conflicts and print exact recovery commands.

### Continue

```bash
echelon land <spec_id> --continue
```

Continue after the user resolved conflicts on the feature branch. It should:

- verify there are no unmerged paths
- create or complete the merge commit if needed
- run verification
- push the feature branch
- retry landing

### Conservative Mode

```bash
echelon land <spec_id> --no-autoresolve
```

Disable automatic conflict resolution. Useful when users want Echelon to orient
and prepare, but not modify conflicted files.

### Prepare Only

```bash
echelon land <spec_id> --prepare-only
```

Prepare and push the feature branch, then stop before merging to default. This
is useful when branch protection or external review is required.

### Strategy Override

```bash
echelon land <spec_id> --strategy merge
echelon land <spec_id> --strategy rebase
```

`merge` is the default. `rebase` is explicit because it may require
`--force-with-lease` and rewrites feature-branch history.

## Landing State Machine

1. **Orient**
   - Resolve feature branch from spec ID.
   - Fetch origin.
   - Read latest harness state.
   - Confirm at least one strategy converged, unless the branch is already
     merged or a PR is already merged.
   - Confirm the project working tree is clean or only has known ignored
     runtime artifacts.

2. **Check Already Landed**
   - If the feature branch no longer exists and spec is marked landed, return
     success.
   - If default branch already contains the feature branch tip, run cleanup and
     return success.

3. **Prefer PR Merge**
   - Find an existing PR for the feature branch, not only a stored state PR URL.
   - If PR exists and merge succeeds, finalize.
   - If PR merge is blocked because the branch is behind or conflicted, prepare
     the feature branch.
   - If PR tooling is unavailable, continue with local preparation/direct merge.

4. **Prepare Feature Branch**
   - Checkout feature branch.
   - Merge default branch into feature branch using `git merge --no-ff`.
   - If merge succeeds, verify and push.
   - If merge conflicts, invoke automatic conflict resolvers.

5. **Automatic Conflict Resolution**
   - Resolve only low-risk conflict classes.
   - Stage resolved files.
   - If all conflicts are resolved, complete the merge commit.
   - If semantic conflicts remain, leave the feature branch in conflict state
     and print `echelon land <spec_id> --continue`.

6. **Verify**
   - Prefer configured `verify_command`.
   - Otherwise reuse the existing local verification detection used by the
     harness.
   - If verification fails, leave the feature branch intact and print the
     failure summary.

7. **Push**
   - Push feature branch to origin.
   - Use normal push for merge strategy.
   - Use `--force-with-lease` only for explicit rebase strategy.

8. **Retry Landing**
   - If PR exists, retry PR merge.
   - If no PR exists, perform direct merge into default branch.
   - Direct merge should be attempted only after feature preparation succeeded.

9. **Finalize**
   - Delete remote feature branch only after confirmed landing.
   - Delete local feature branch with safe `git branch -d`.
   - Clean harness worktrees.
   - Mark spec status as landed.
   - Ensure the working tree is on the default branch.

## Automatic Conflict Resolvers

### `.gitignore`

Resolve by union:

- keep both sides
- preserve comments where practical
- deduplicate exact lines
- group common sections if already present
- ensure `.DS_Store`, `runs/`, and local Echelon runtime artifacts remain
  ignored when they were ignored on either side

If a tracked file becomes ignored by the resolved `.gitignore`, remove it from
the merge commit when it is a known runtime or OS artifact.

### `.gitattributes`

Resolve by union:

- keep LFS rules from either side
- deduplicate exact lines
- stop for conflicting filters on the same path pattern

### Runtime and OS Artifacts

Drop known artifacts from the merge when they are tracked only because of older
branch state:

- `.DS_Store`
- local harness runtime files
- temporary build output

Do not drop source, spec, task, plan, or resource files.

### Append-Only Markdown

For selected docs where append-only merge is safe:

- keep both non-overlapping sections
- deduplicate identical headings only when body text is identical
- stop when the same heading has different body text

This resolver should be opt-in per path pattern, not global for all Markdown.

### Package Locks

Do not hand-edit lock conflicts. If the package manager is detected:

- restore both manifests to resolved state if possible
- rerun the package manager lock generation command
- stage the regenerated lock

If the package manager cannot be detected, stop for user resolution.

## Error Handling

### Dirty Working Tree Before Landing

If tracked changes exist before landing, stop and print:

- current branch
- changed tracked files
- options: commit, stash, or rerun after cleanup

Untracked `runs/` and Echelon runtime files should not block landing.

### Direct Merge Failure

If direct merge into default fails after feature preparation:

- abort the merge if possible
- restore the previous branch if possible
- print the failed command and conflicted files
- do not delete branches or clean worktrees

### Feature Preparation Conflict

If preparation leaves semantic conflicts:

- stay on the feature branch
- leave conflict markers for the user
- print conflicted files
- print `echelon land <spec_id> --continue`

### Verification Failure

If verification fails after preparation:

- leave feature branch with the preparation commit
- do not merge to default
- print verification failures
- print rerun command after fixes

## Test Strategy

Unit tests should cover:

- PR merge path still succeeds and finalizes.
- No-PR direct merge succeeds after feature branch is already up to date.
- Direct merge conflict is aborted and leaves repo clean.
- Default land prepares feature branch by merging default branch into it.
- `.gitignore` add/add conflict is auto-resolved by union.
- Ignored `.DS_Store` is dropped from the merge.
- Semantic source conflict stops with `--continue` guidance.
- `--continue` completes after conflicts are manually resolved.
- Verification failure blocks final merge.
- Feature branch push uses normal push for merge strategy.
- Rebase strategy requires explicit opt-in and uses force-with-lease only there.

Integration-style tests with temporary git repositories should cover:

- Diverged `main` and feature branch with only `.gitignore` conflict.
- Diverged branches with source-code conflict.
- Existing PR URL path.
- Missing PR tooling direct-merge path.
- Idempotent rerun after successful landing.

## Rollout Plan

1. Add a focused `LandPreparationResult` model and preparation helper.
2. Add conflict resolver helpers for `.gitignore`, `.gitattributes`, and
   known runtime artifacts.
3. Refactor `land()` to call preparation before direct merge.
4. Add CLI flags: `--continue`, `--no-autoresolve`, `--prepare-only`,
   `--strategy`.
5. Improve terminal banners with exact branch, action, and next-command output.
6. Extend auto-land to use the same improved `land()` behavior.

## Non-Goals

- Fully automatic semantic source-code conflict resolution.
- Force-pushing by default.
- Replacing GitHub/GitLab branch protection or review policy.
- Deleting feature branches before landing is confirmed.
- Cleaning all untracked local runtime directories as part of landing.
