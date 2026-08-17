# RE v2 Polyrepo Source Snapshot Design

**Date:** 2026-08-17  
**Status:** Approved for planning  
**Scope:** Correct the EGR-164 pilot snapshot boundary for declared-source
workspaces without implementing L1-L4 analysis, cross-run reuse, synthesis, or
partial-source operation.

## Problem

RE v2 creation currently calls `capture_source_snapshot()` on the orchestration
workspace root. That boundary is wrong for a polyrepo workspace:

- a dirty orchestration checkout falls back to a content snapshot and scans
  installed tooling, generated RE output, dependency trees, and ordinary
  package symlinks;
- a clean orchestration checkout uses its Git commit, but child repositories
  under an ignored `sources/*` tree are absent from that commit; and
- the partition manifest is derived independently from the live workspace, so
  it can name source paths that do not exist in the pinned snapshot.

The real OptaSearch workspace reproduced the first failure at an installed
`.claude/skills/.../SKILL.md` symlink. Its root repository ignores
`sources/*`, proving that simply excluding `.claude` would make clean capture
silently omit the inputs RE is meant to inventory.

## Decision

RE v2 will capture one atomic **composite workspace snapshot** from the source
roots returned by workspace discovery. It will not capture the orchestration
root as source material.

Every declared source must be backed by a Git repository whose worktree is
clean. A source is dirty when Git reports tracked changes, staged changes,
untracked non-ignored paths, or dirty/uninitialized submodule state. Git-ignored
content does not make a source dirty and is not captured.

If any source is dirty or is not Git-backed, creation stops before a run store
is created and before `runs/.current-re` changes. The diagnostic identifies
every offending source and recommends committing, stashing (including
untracked files), or reverting/removing the changes before retrying. RE v2 does
not silently omit, copy, or reinterpret dirty source bytes.

## Considered approaches

### Composite declared-source snapshot — selected

Materialize every declared source at its pinned Git commit beneath its original
workspace-relative path, then publish the combined tree and manifest as one
snapshot. This preserves the existing controller contract of one
`source_snapshot_id`, fixes the polyrepo boundary, and gives the partition
manifest one exact snapshot to reference.

### Expand root exclusions — rejected

Adding `.claude`, `.echelon`, `re`, and dependency directories would be an
open-ended denylist. It would still omit ignored child repositories in the
clean-root path and would couple correctness to each workspace's tooling
layout.

### Make every controller object carry a vector of source snapshots — deferred

Per-source snapshot identities are a reasonable longer-term protocol, but
changing every artifact key, work item, candidate, ledger receipt, recovery
check, and publication key is larger than this compatibility fix. The
composite manifest retains the component identities needed for such a future
migration.

## Snapshot contract

New runs use engine protocol `2.1` and snapshot kind
`workspace-git-composite`. Existing protocol `2.0` runs retain their current
`git-worktree` or `content-snapshot` loader and remain continuable without
migration.

The composite manifest contains:

- a capture schema/version and snapshot kind;
- a canonical, source-ID-sorted component list;
- for each component: source ID, workspace-relative path, repository-relative
  path, pinned commit, recursive submodule identities, and component tree
  digest;
- the flat canonical inventory of files under the composite read root; and
- the complete effective exclusion policy.

Absolute checkout paths and run IDs are operational data and do not contribute
to snapshot identity. The snapshot ID hashes the canonical manifest identity,
including the ordered component records and flat inventory.

The read tree preserves each source's workspace-relative path. For example,
source `pressbox-search-api` remains available at
`sources/pressbox-search-api` beneath the snapshot root. Orchestration files,
installed provider packages, prior `re/` artifacts, `runs/`, and ignored build
or dependency output are absent because they are not declared Git source
content.

Declared source paths must be canonical, unique, inside the workspace, and
non-overlapping. Source IDs must retain the existing safe-ID contract. A
declared directory may be a repository root or a subtree of an owning
repository. Multiple non-overlapping sources may share one owning repository;
the repository is checked and materialized once, while each declared subtree
gets its own component record.

Tracked symlinks and special files remain rejected. This fix removes unrelated
tooling and ignored dependency symlinks from the capture boundary; it does not
weaken the provider filesystem boundary.

## Capture flow

1. Discover and validate the workspace source declarations.
2. Resolve the owning Git repository, commit, and repository-relative path for
   every source.
3. Preflight all distinct repositories and collect all failures. Require a
   valid `HEAD`, initialized recursive submodules, and empty porcelain status
   with ignored files excluded.
4. Acquire deterministic repository/source locks in canonical path order.
5. Recheck the pinned commits and clean state while holding the capture locks.
6. Create detached temporary worktrees at the pinned commits, materialize
   recursive submodules from local Git object stores without network access,
   and copy only each declared subtree into one private composite stage.
7. Reject collisions, symlinks, special files, missing declared subtrees, or
   any source-set mismatch.
8. Recheck the live repositories. If a commit or clean-state proof changed,
   discard the stage and fail rather than publish mixed-time bytes.
9. Generate and validate the canonical component and flat inventories, make
   the staged tree immutable, and atomically publish it using the existing
   commit-marker protocol.
10. Derive the partition manifest from the published component list. Create
    the run store and activate the run only after the snapshot and partition
    source sets match exactly.

Crashes or validation failures may leave only recoverable private staging
state. They never expose a committed snapshot, create a v2 run, or replace the
active-run pointer.

## Runtime and recovery

`CapturedSnapshot` and validation gain explicit support for the composite kind.
Recovery checks the same manifest bytes, component identities, flat inventory,
commit marker, permissions, and source-set/partition agreement before provider
or publication side effects.

Providers continue receiving one read-only snapshot root. The planner,
candidate protocol, ledger, budgets, and deterministic L0 artifact graph do
not change. Inventory evidence now describes actual declared source bytes
rather than orchestration state.

Protocol validation accepts both:

- `2.0` with the legacy snapshot kinds for existing runs; and
- `2.1` with `workspace-git-composite` for new runs.

There is no in-place conversion between protocols or snapshot kinds.

## Diagnostics

A cleanliness failure is concise and actionable. It lists each source ID and
repository with a bounded summary of staged, modified, untracked, or submodule
state, followed by guidance equivalent to:

> Commit the source changes, stash them including untracked files, or
> revert/remove them, then retry `echelon re run --engine v2`.

The command exits nonzero without creating `runs/<run-id>` and without changing
`runs/.current-re`. A non-Git source is reported separately as unsupported by
the clean-source v2 pilot.

## Test strategy

Regression tests first reproduce the production workspace shape and must fail
on the current implementation:

- an orchestration repository ignores `sources/*` and contains an unrelated
  tooling symlink;
- two declared child repositories are clean and contain distinct tracked
  files;
- ignored dependency trees contain `.bin` symlinks; and
- the composite snapshot contains both declared trees and none of the
  orchestration/tooling/ignored content.

Additional tests cover:

- all dirty-state categories, aggregated source diagnostics, and remediation
  text;
- no run directory or active-pointer mutation on preflight failure;
- non-Git, missing, overlapping, duplicate, and escaping source declarations;
- declared subtrees and multiple sources sharing one repository;
- recursive submodule identity and offline materialization;
- source mutation between preflight and publication;
- crash prefixes and stale-stage recovery for atomic composite publication;
- tampered component records, flat inventory, source-set mismatch, and legacy
  protocol `2.0` continuation; and
- an end-to-end shadow/continue/status/replay run against a representative
  polyrepo fixture.

After the automated gates pass, install Echelon and rerun the pilot against
`/Users/michalbachorik/work/optasearch`. The expected first result is an
actionable dirty-source report if any declared repository is dirty. Once those
sources are clean, shadow and live L0 inventory must complete without reading
the dirty orchestration checkout or its installed symlinks.

## Out of scope

- Capturing dirty or non-Git declared sources.
- Supporting tracked symlinks inside source inputs.
- L1-L4 producers, semantic repair, cross-run reuse, workspace synthesis, or
  partial finalization.
- Changing the JSON `continuable` meaning; the shadow-status inconsistency is a
  separate operator-status issue.
