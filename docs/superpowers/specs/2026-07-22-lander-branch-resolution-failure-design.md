# Lander Branch-Resolution Failure Design

## Problem

`GitOps.find_feature_branch()` currently catches mirror fetch and branch-listing
errors and returns `None`. The landing path cannot distinguish that failure from
a successful lookup that found no feature branch. It consequently reports the
spec as already landed, performs cleanup, returns `True`, and causes auto-land to
print `Auto-landed successfully!` even though branch resolution failed.

## Design

Branch lookup will preserve the existing `str | None` success contract while
changing its failure contract:

- Return the branch name when a matching branch exists.
- Return `None` only when the mirror was successfully queried and no matching
  branch exists.
- Raise `GitOpsError` when fetching or listing mirror branches fails.

`land()` will catch `GitOpsError` from feature-branch lookup, emit a clear
landing-blocked diagnostic, return `False`, and stop before legacy fallback,
worktree cleanup, branch deletion, readiness checks, or merge operations.
The existing auto-land caller already treats `False` as failure and therefore
will not print its success message.

This keeps the change narrow: successful lookup, genuine absence, legacy
harness-branch fallback, and normal landing behavior remain unchanged.

## Error Handling

The failure message will identify the spec and underlying branch-resolution
error and instruct the operator to repair repository/mirror access before
retrying. A lookup failure is never interpreted as evidence that landing has
already occurred.

## Tests

Regression coverage will prove:

1. `find_feature_branch()` propagates a mirror fetch failure.
2. `find_feature_branch()` propagates a branch-listing failure.
3. `land()` returns `False` on branch-resolution failure and does not invoke
   cleanup or branch deletion.
4. Auto-land does not print `Auto-landed successfully!` when `land()` returns
   `False` (the existing caller-level test will be retained or strengthened).

Focused tests will run first, followed by the complete relevant unit suite.

## Non-goals

- Changing the feature-branch naming scheme.
- Repairing mirror URLs automatically.
- Refactoring landing into a new result type.
- Changing genuine idempotent already-landed behavior.
