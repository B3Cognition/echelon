# Spec Catalog Publication Design

**Date:** 2026-07-19

**Status:** Approved for implementation planning

**Scope:** Publish committed spec snapshots from canonical local Phase A branches to the local default branch

## Summary

Echelon will add `echelon spec publish <id>` and `echelon spec publish --all`.
The commands publish only the matching `specs/<id-slug>/` directory from each
selected local Phase A branch into one commit on the local default branch. They
do not merge implementation history, source code, or branch ancestry. Source
branches remain unchanged and available for future work.

This makes the default branch a durable, clone-friendly catalog of published
specifications. `echelon wiki build` remains branch-local and can build a
complete workspace view from the default branch without learning how to inspect
arbitrary Git branches.

## Problem

Echelon creates sibling Phase A branches. Each branch may contain a spec that is
not present on the default branch, so a wiki generated from the default branch
cannot show the whole workspace. Making the wiki branch-aware would introduce
selection, duplication, stale-branch, and provenance ambiguity. Merging entire
spec branches into the default branch would risk publishing implementation
changes and would couple documentation visibility to delivery.

The catalog therefore needs a deliberate spec-only publication boundary.

## Goals

- Publish one selected spec or every eligible local spec atomically.
- Keep the default branch as the authoritative human catalog.
- Copy only committed canonical spec artifacts.
- Retain every source branch without changing or deleting it.
- Record the exact source branch and commit for each snapshot.
- Make repeated publication of unchanged snapshots a no-op.
- Keep publication local: no implicit fetch, push, or network access.
- Provide CLI help that makes the spec-only behavior unmistakable.
- Preserve `echelon wiki build` as a simple current-branch operation.

## Non-goals

The initial version will not:

- Discover remote-tracking branches.
- Run `git fetch` or publish to a remote.
- Merge complete feature branches or implementation history.
- Delete, rename, reset, rebase, or otherwise mutate source branches.
- Publish `runs/`, `re/`, source repositories, or arbitrary branch content.
- Resolve semantic conflicts between two branches claiming the same numeric ID.
- Create a pull request instead of a local default-branch commit.
- Make the wiki inspect Git branches directly.
- Automatically switch the caller to the default branch.

## Alternatives

### Merge complete branches

This uses ordinary Git ancestry but can publish implementation changes and makes
catalog visibility dependent on delivery readiness. It is rejected.

### Build a branch-aware wiki

This avoids changing the default branch but requires policies for duplicates,
stale branches, missing remote refs, and competing revisions. It is rejected as
the primary model.

### Publish spec-only snapshots

This copies the committed matching spec tree into a default-branch commit while
retaining the source branch. It gives people and the wiki one durable catalog
without conflating specification publication with implementation landing. This
is the selected approach.

## Command contract

```text
echelon spec publish 003
echelon spec publish 003-add-feature-opta-search
echelon spec publish --all
```

Exactly one of a positional spec identity or `--all` is required. Numeric
identities use exact zero-padded prefix matching and must resolve uniquely.

Help text must state that the command:

- publishes committed spec snapshots to the local default branch;
- copies only each branch's matching `specs/<id-slug>/` directory;
- does not merge implementation history;
- does not fetch, push, delete, or change source branches;
- requires clean selected spec directories and a clean checked-out default
  branch worktree; and
- considers canonical local branches only.

Successful output lists selected specs, source branches and commits, changed or
no-op disposition, the resulting default-branch commit, retained source
branches, and explicit next steps. It always states that nothing was pushed.

## Canonical branch selection

Eligible refs come only from `refs/heads/`. Remote-tracking refs are excluded.
The default branch and auxiliary namespaces are excluded.

A canonical Phase A branch name matches the repository's spec identity contract:
`<NNN>-<slug>`, using a numeric prefix of at least three digits and a normalized
lowercase slug. The branch must contain `specs/<branch-name>/spec.md` at its committed tip.
That matching directory is the branch's only publication contribution.

A branch may also contain specs inherited from its base. Those directories are
ignored. Backup, harness, Codex, temporary, and other noncanonical branches are
ignored even if they contain spec files.

For `publish <id>`, a full canonical name selects that exact branch. A numeric ID
selects the unique canonical local branch with that prefix. Zero or multiple
matches fail and list the candidates.

For `publish --all`, every eligible canonical local branch is selected in stable
branch-name order. Multiple branches claiming the same numeric ID are a conflict
and abort the whole operation.

If the default branch already contains a differently named `specs/<id>-*/`
directory with the same numeric identity, publication also aborts. The command
never guesses whether a rename or replacement was intended.

## Publication data flow

1. Resolve the configured local default branch through Echelon's existing Phase
   A default-branch contract.
2. Enumerate eligible local branches and resolve the requested selection.
3. Inspect every selected committed Git tree without checking out the source
   branches.
4. Validate the source worktree, identity, required `spec.md`, destination
   collision, and default worktree preconditions.
5. Materialize each matching committed spec directory into an isolated staging
   directory.
6. Add deterministic publication provenance to the staged snapshot.
7. Replace only the selected destination spec directories in the default-branch
   worktree.
8. Stage only those directories, verify the staged diff, and create one commit.
9. On success, report the resulting commit and retain all source branches.
10. On failure before commit, restore only publication-owned destination paths.

Specs not selected remain untouched. Republishing replaces the destination
directory exactly so files removed from the source snapshot cannot survive as
stale catalog entries.

## Provenance

Each destination snapshot contains `.echelon-publication.json`:

```json
{
  "schema_version": 1,
  "spec_id": "003-add-feature-opta-search",
  "source_branch": "003-add-feature-opta-search",
  "source_commit": "0123456789abcdef..."
}
```

The manifest exists only in the default-branch snapshot; publication does not
write it back to the source branch. Keys are sorted and the file ends with one
newline. No wall-clock timestamp is stored, so an unchanged source commit
produces byte-identical output and no new commit.

Wiki discovery reads this manifest into optional spec publication provenance.
The spec overview displays the source branch and abbreviated commit when present.
Specs without a manifest remain supported.

## Git and worktree behavior

The commands create a local commit only. They never fetch, push, stash, or alter
source refs.

If the default branch is checked out in the caller's worktree, that worktree is
used. If it is checked out in another worktree, Echelon may use that worktree only
when it is clean. If the default branch is not checked out, Echelon creates a
temporary worktree for the local default branch, commits there, and removes the
temporary worktree afterward.

Any checked-out default-branch worktree must be completely clean. Publication
refuses dirty state rather than stashing or discarding it. The default ref is
captured before staging and checked again before commit so concurrent changes
abort publication.

If a selected source branch is checked out in any worktree and its matching spec
directory has staged, unstaged, or untracked changes, publication fails. The
command never silently publishes an older committed snapshot while newer spec
work is visible in a worktree.

The publication commit contains only selected `specs/<id>/` paths. Its message
identifies the published IDs and uses Echelon's normal commit-attribution
trailers. Source branch refs remain byte-for-byte unchanged.

## Atomicity and recovery

Selection, source validation, destination collision checks, and staging complete
before any default-branch path is modified. `--all` is one transaction: any
invalid, ambiguous, dirty, or conflicting source prevents every publication.

After destination mutation begins, Echelon tracks the exact owned paths. If
copying, staging, validation, or committing fails, it restores those paths to the
captured default commit and removes newly created untracked publication paths.
It never resets unrelated paths.

If there is no staged difference, the command succeeds as a no-op and creates no
commit. A failed temporary-worktree cleanup is reported without deleting source
branches or hiding a successful commit.

## Errors and operator guidance

Errors name the branch, spec path, default worktree, or conflicting identity and
give a concrete recovery action. Important cases include:

- no canonical local branch matches the requested identity;
- more than one branch claims a numeric ID;
- a canonical branch lacks its matching committed `spec.md`;
- a selected spec has uncommitted work in a checked-out worktree;
- the default branch is absent or its worktree is dirty;
- the default ref changes during publication;
- the destination path escapes `specs/` or collides with another identity; and
- Git staging or commit creation fails.

Successful output includes these next steps:

```text
git push origin <default-branch>
git switch <default-branch>
echelon wiki build
```

The switch instruction is omitted when the caller already occupies the default
branch. The output explicitly says source branches were retained and nothing was
pushed.

## Component boundaries

### Publication service

A focused Python module owns canonical branch enumeration, identity resolution,
Git-tree materialization, worktree selection, provenance writing, exact snapshot
replacement, commit creation, rollback, and structured results. It has no Typer
or terminal-formatting dependency.

### CLI adapter

The Typer command validates mutually exclusive arguments, invokes the service,
and presents structured results and recovery errors. Help is the public safety
contract and uses concrete examples.

### Wiki integration

Wiki discovery optionally parses `.echelon-publication.json`; rendering displays
provenance without changing freshness or canonical-input semantics.

## Test strategy

Unit tests use real temporary Git repositories and cover:

- canonical local-branch filtering and exclusion of auxiliary/remote refs;
- exact and numeric identity resolution, including ambiguity;
- inherited-spec isolation and matching-directory selection;
- missing committed `spec.md`;
- dirty selected source worktrees;
- dirty current or secondary default-branch worktrees;
- exact replacement and stale-file removal;
- deterministic publication provenance;
- source branch immutability;
- one atomic commit for `--all`;
- rollback after staged publication failure;
- no-op republishing;
- current, secondary, and temporary default-worktree paths;
- concurrent default-ref change detection;
- CLI mutual-exclusion errors, output, and complete help text; and
- wiki-visible branch/commit provenance with legacy manifest absence.

Focused integration verification runs the publication, spec lifecycle, CLI,
wiki, release metadata, and Git worktree suites. The full repository suite is
compared with the five known unrelated baseline failures accepted during the
3.6.0 human-wiki release.

## Documentation and issue tracking

The README command table and human-wiki guidance will explain that users publish
spec snapshots to the default branch before building a complete catalog. The
changelog will reference the GitHub enhancement issue and describe the spec-only
boundary. The issue will capture why default-branch publication is preferred to
branch-aware wiki discovery.
