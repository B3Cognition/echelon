# Polyrepo Legacy Landing Selection Design

## Problem

Landing spec 911 is blocked even though its canonical lifecycle is
`ready_to_land` and its fulfillment report records verified commit
`f7d2e147cb8add7c41d5bd9c4224b6b44fe7becb`.

Two independent defects cause the block:

1. The active Phase A guard compares the orchestration workspace branch with
   the implementation branch in a separate target repository. Those branch
   names belong to different repositories and are not comparable.
2. Legacy branch discovery chooses the largest `iter-N`. A later-numbered
   branch can belong to an older failed build, while the current converged build
   records a smaller outer iteration.

## Design

### Cross-repository active-authoring guard

The active Phase A branch guard remains unchanged for single-repository
landing, where landing can disturb the active authoring checkout.

For polyrepo landing, where `project_dir` is different from the orchestration
`wrapper_project_dir`, target Git operations cannot switch or modify the Phase A
workspace checkout. Landing therefore skips branch-name equality and relies on
the already-resolved spec identity and target path. Invalid or unreadable active
Phase A state remains blocking only when landing operates in that same
repository.

### Legacy implementation branch selection

Landing resolves a legacy harness branch from the current delivery build before
falling back to numeric branch discovery:

1. Read the canonical current-build marker for the requested spec from the
   target harness root.
2. Read strategy state files from that build and require exactly one successful
   terminal delivery candidate. Zero or multiple candidates fail closed.
3. Derive that candidate's recorded strategy and outer iteration.
4. Construct `harness/<spec-alias>/<strategy>/iter-<outer_iter>`.
5. Require that branch to exist in the target repository.
6. Read the canonical fulfillment report's `verified_commit` and require it to
   be an ancestor of the candidate branch.

If current-build evidence is absent or is a genuinely older state shape that
cannot identify a candidate, landing may use the existing legacy fallback. If
current-build evidence exists but conflicts with the branch or verified commit,
landing fails closed instead of choosing a different iteration.

### Landing execution safety

The existing dirty target checkout is not discarded. Before landing, its exact
HEAD, status, and staged/unstaged hashes are captured. If landing requires a
clean checkout, the two tracked dependency changes are placed in a named Git
stash, landing and verification run, and the stash is restored afterward. Any
stash-restore conflict stops for inspection without deleting the stash.

The clean stale iter-4 worktree may be removed while retaining its branch. That
cleanup only releases a mirror worktree registration; it does not delete
verified commits or branches.

## Error Handling

- Ambiguous or contradictory build/branch/provenance evidence blocks landing.
- A candidate branch that does not contain `verified_commit` blocks landing.
- Single-repository active-authoring protection remains fail-closed.
- Polyrepo landing never switches the orchestration workspace checkout.
- Dirty target changes are restored only after landing completes or safely
  stops; their stash is retained on restore failure.

## Tests

- Polyrepo landing does not compare the Phase A workspace branch with the target
  implementation branch.
- Single-repository landing still blocks a different active authoring branch.
- Current converged build at iter-1 wins over an older failed iter-4 branch.
- The selected branch must contain the fulfillment report's verified commit.
- Conflicting current-build provenance blocks rather than falling back.
- Existing fallback behavior remains for runs without usable current-build
  evidence.

## Success Criteria

- `echelon delivery land 911` selects `harness/911/default/iter-1`, not iter-4.
- Landing is not blocked by the orchestration workspace's Phase A branch.
- Prosaic verification passes after merge.
- Spec 911 becomes `landed` only after verified work reaches the target default
  branch.
- The pre-existing dependency changes are preserved exactly.
