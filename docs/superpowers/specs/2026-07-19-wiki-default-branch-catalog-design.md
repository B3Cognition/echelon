# Default-Branch Wiki Catalog Design

**Date:** 2026-07-19  
**Issue:** Follow-up to #166 local spec catalog publication

## Problem

`echelon spec publish --all` commits canonical spec snapshots to the configured
local default branch without moving the caller's checkout. `echelon wiki build`
then reads `Path.cwd()`, so running both commands from a Phase A branch builds a
wiki from that feature branch rather than from the newly published catalog.

The same mismatch affects `echelon wiki status`, input snapshots, and automatic
refresh. A wiki built from the default branch can appear stale when inspected
from a feature branch, while a publish performed from a feature branch can fail
to trigger refresh because that checkout's inputs did not change.

## Goals

- Build the wiki from the configured local default-branch catalog while leaving
  the caller on the active Phase A branch.
- Keep the generated vault at the caller workspace's existing
  `.echelon/runtime/wiki/` path.
- Make build, status, input snapshots, and automatic refresh use the same source.
- Preserve existing behavior for non-Git workspaces and callers already on the
  default branch.
- Honor `.echelon/local.yml` over `.echelon/config.yml` when resolving the
  default branch and safe workspace/source identity.
- Never fetch, push, stash, or change a caller branch.

## Non-goals

- Making wiki discovery branch-aware across arbitrary feature branches.
- Publishing specs as part of `wiki build`.
- Including uncommitted feature-branch artifacts in the default-branch catalog.
- Installing or launching Obsidian.

## Considered approaches

### 1. Switch the caller to the default branch

This is the smallest implementation, but it is unsafe and disruptive. It can
fail on dirty Phase A work, disturb an active execution lease, and leave the user
on a different branch after a read-only command.

### 2. Read the default Git tree directly

`git archive`, `git show`, and tree hashing could avoid a worktree. However, the
existing discovery and rendering pipeline intentionally operates on filesystem
paths, reads Git history for recent changes, and copies attachments. Recreating
those capabilities over Git objects would duplicate substantial logic.

### 3. Use a detached temporary worktree (recommended)

Resolve the configured local default branch, attach a read-only detached
worktree at its captured commit, run the existing discovery/rendering pipeline
against that source, and publish the generated vault into the caller workspace.
This reuses proven behavior while never moving or modifying the caller checkout.

## Architecture

### Catalog source context

Add an internal context manager in `echelon.wiki.service` that yields an immutable
catalog-source record containing:

- caller workspace root;
- source root used for discovery and hashing;
- source branch when Git-backed;
- exact source revision;
- whether canonical source inputs are dirty; and
- whether the source is temporary.

Resolution uses `get_full_resolved_config`, followed by the existing
`resolve_phase_a_default_branch` contract. This preserves
`.echelon/local.yml` precedence and the repository's `main`/`master` fallback.

If the caller is already on the default branch, the caller root remains the
source. This preserves the existing ability to build and inspect uncommitted
default-branch artifact edits.

If the caller is on another branch or detached, create a temporary detached
worktree at the captured default commit. Copy the caller's optional
`.echelon/local.yml` into that temporary worktree so safe resolved workspace and
source identity remains consistent. Remove and prune the worktree before the
staged vault replaces the previous generated vault.

If the workspace is not Git-backed or has no resolvable local default branch,
fall back to the caller root. This keeps current standalone/non-Git usage and
unit-test fixtures working.

### Separate source and output roots

`build_wiki(project_root)` continues to expose the caller root as its public API.
Internally:

1. Allocate staging under the caller's `.echelon/runtime/` directory.
2. Enter the catalog source context.
3. Discover, hash, and render from the context's source root.
4. Normalize the model's public workspace root to the caller root.
5. Write manifest provenance for the catalog branch, revision, and dirty state.
6. Exit and clean up the source context.
7. Atomically replace the caller's generated vault.

This ordering ensures a temporary-worktree cleanup failure cannot hide a
successfully replaced vault: cleanup completes before publication.

`WikiBuildResult` exposes optional catalog branch and revision fields so the CLI
can print what it indexed.

### Consistent status and refresh

`wiki_status`, `capture_input_snapshot`, and `refresh_after_changed_command`
enter the same catalog source context before hashing inputs. Consequently:

- a default-catalog vault remains fresh while the caller stays on a feature
  branch;
- a new publish commit makes status stale even without switching branches; and
- an existing auto-refresh-enabled vault rebuilds after `spec publish` changes
  the default catalog.

`wiki clean` remains output-only and does not need a source context.

## Manifest compatibility

Keep the current manifest schema version. Add optional catalog provenance:

```json
{
  "catalog_branch": "master",
  "workspace_revision": "0123456789abcdef...",
  "workspace_dirty": false
}
```

Older valid manifests remain readable because validation already ignores
unknown/missing provenance fields and requires only the existing ownership,
schema, input, and output fields.

## Error handling and safety

- Never fetch or infer remote refs; only the resolved local default ref is used.
- A failure to create, read, remove, or prune the temporary worktree fails the
  build before replacing an existing vault.
- Staging is deleted after any failure.
- The caller's branch, HEAD, index, and working files remain untouched.
- A concurrent default-ref update cannot make the built vault internally
  inconsistent because discovery is pinned to the captured commit. A later
  status check observes the new catalog hashes and reports stale.
- Temporary local-config copies are removed with the worktree and are never
  included verbatim in the safe wiki configuration payload.

## CLI behavior

`echelon wiki build` prints the generated location as before and additionally
prints the catalog branch and abbreviated revision when Git-backed. It does not
print or perform `git switch`.

The `spec publish` next-step output can simply recommend `echelon wiki build`
because wiki source selection is now independent of the caller branch.

## Testing

Add real-Git tests that reproduce the reported sequence:

1. Create `master` with spec 001.
2. Create and remain on branch 004, which sees only 001 and its own 004.
3. Commit published 001–004 snapshots to `master` through another worktree.
4. Run `build_wiki` from branch 004.
5. Assert the caller branch and HEAD are unchanged and the vault contains all
   four default-branch specs.

Also verify:

- status is fresh immediately after the cross-branch build;
- a later default-branch catalog commit makes status stale;
- automatic refresh observes a publish performed from a feature branch;
- `.echelon/local.yml` overrides the committed default-branch setting;
- temporary worktrees are removed;
- non-Git and on-default callers retain existing behavior; and
- CLI output identifies the indexed catalog source.
