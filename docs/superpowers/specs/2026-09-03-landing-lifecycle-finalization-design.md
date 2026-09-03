# Landing Lifecycle Finalization Design

**Date:** 2026-09-03

## Problem

Successful delivery landing currently finalizes only the implementation target.
In a polyrepo workspace, delivery history is appended after the last workspace
spec commit, `land` then mutates the spec status to `landed`, and neither change
is committed or published to the workspace default branch. The authoring
checkout remains on the spec branch and dirty. `echelon spec status` continues
to interpret the completed Phase A run as buildable and reports `READY TO BUILD`
even though `echelon delivery status` reports the spec as landed.

A separate hygiene issue exists for implementation targets: generated verifier
output can remain visible to Git when the project does not ignore it. Echelon
must never silently delete unknown user files, but it also must not claim a
fully successful landing while either owned checkout is dirty.

## Design

### Workspace finalization transaction

Add one landing finalizer used by both feature-branch and branchless landing.
It will:

1. Resolve the canonical spec directory and write `status: landed`.
2. Stage only `specs/<spec-id>`, run the existing staged-secret scan, and commit
   any terminal status/history/index changes with Echelon commit metadata.
3. For a distinct orchestration workspace, reuse `publish_specs()` to publish
   the exact committed spec snapshot to the configured default branch.
4. Switch the orchestration checkout to its default branch after publication.
5. Clear the active authoring pointer only after commit and publication succeed.
6. Verify that the orchestration checkout has no remaining tracked or untracked
   changes. A residual path makes landing incomplete and is reported exactly.

For a monorepo, the spec is already on the implementation default branch after
the product merge. The finalizer commits the bounded spec subtree directly and
does not invoke spec publication.

The operation is idempotent: a repeated landing sees no spec changes and an
already-published snapshot, then only verifies checkout and pointer state.

### Status authority

`echelon spec status` will consult the canonical published `spec.md` lifecycle
status before calculating Phase A build readiness. `landed` is terminal and
renders a dedicated `LANDED` next-step panel with no delivery command. Phase A
run state remains visible as provenance but cannot override the canonical
terminal lifecycle state.

### Clean-checkout invariant

Landing will inspect full Git status, including untracked files, before
reporting success. Echelon may restore known *tracked* generated drift as it does
today, but it will not delete untracked files. Any remaining path blocks the
success claim with exact remediation.

Delivery-generated verifier directories remain sandbox/worktree-local. Projects
that intentionally generate host-side reports must ignore those paths. The
browser 3D demo will add `test-results/`, `playwright-report/`, `blob-report/`,
and `coverage/` to its committed `.gitignore`; existing files are preserved.

## Failure semantics

The implementation target merge cannot be rolled back safely. If workspace
commit/publication/final checkout fails after the target merged, `land()`
returns false and reports that implementation is merged but lifecycle
finalization remains pending. Re-running `echelon delivery land <spec-id>`
finishes the idempotent finalization.

## Verification

Regression coverage must prove polyrepo commit/publication/checkout cleanliness,
monorepo bounded commit behavior, branchless idempotence, publication failure,
untracked-residue refusal, landed status rendering, and preservation of unknown
untracked files.
