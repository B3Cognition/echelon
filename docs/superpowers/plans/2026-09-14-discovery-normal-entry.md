# Managed discovery normal entry

Use executing-plans inline and test-driven development; independent read-only
review, no implementation delegation. This implements the already approved
managed-discovery integration design, following completion binding `7de7e433`.

## Checkpoint

- [x] Add an internal explicit selection to normal `SquadController.run`, not a
  CLI/config activation flag. Independently select the existing bootstrap claim
  and input tree. Explicit creation is separate from resume; never initialize
  identity storage or reconstruct missing established state.
- [x] Authenticate that selection under the existing execution leases. Resume
  pending managed completion before testing support for the destination phase.
  Keep manual, human-input and legacy admission exclusions intact.
- [x] Dispatch the complete six-artifact greenfield discovery operation using
  the existing neutral inspection provider, reservation and review owners.
  Reuse prepared-result/graph routing, sealed publication and durable completion.
  Do not add a controller loop, journal, publication engine or allocator.
- [x] Stop at the graph-selected unsupported successor without dispatching it.
  Prove normal entry/restart, exact IDs/references, both providers and all three
  autonomy modes, input/selection drift, interruption and usage accounting.
- [x] Reconcile the seven obsolete managed-legacy integration expectations;
  preserve the actual fail-closed exclusion rather than allowing legacy calls.
- [x] Run affected tests, obtain independent review, record evidence and commit.

## Full activation gates still remaining

Normal discovery admission is not full activation. Accepted-baseline repair and
its evidence/reference regression, later producer/writer coverage (including
FR/NFR/AC/T/ISS), real provider acceptance, public selection, installation and a
fresh bounded live trial must still be completed. Preserve the existing deferred
scope decisions. Do not touch the stopped smoke workspace, AGENTS.md, CLAUDE.md,
legacy build, or existing identity histories. No push or merge.

## Earlier evidence and checkpoint contract decision

The normal entry uses explicit `managed_discovery={bootstrap: <independent
selection>, input_tree: <selected path>}` and separate creation/resume intent.
There is no public CLI/config switch. All six discovery outputs publish through
the existing owners; the actual workflow successor is `phase1-synthesizer`, not
the simplified `phase1-what` destination used in earlier completion fixtures.
Both provider identities and guided/semi/banzai pass with scripted external
processes. This is not real-provider acceptance.

Review-driven red/green regressions fixed:

- Accepted receipt usage belongs in the successful prepared route, not the
  routing failure-accounting path. Missing checkpoint prestate and failed state
  advance cannot double-charge retained model work. The exact existing
  `controller_state_contract_validation_failed` retry policy is preserved.
- Fresh enrollment refuses inherited discovery dispatches. The existing
  operation-selection state commit records its one outer phase dispatch
  atomically; replay does not increment again or reset inner attempts.
- A never-routed completion draft can be discarded only after its exact protected
  association and absence of both Squad and identity authority are checked.
  Published/released recovery is not eligible. Interrupted disposal between the
  external and completion stages additionally proves original sources through
  the retained empty inspection transaction before finishing cleanup.

Observed checks: 22 normal-entry tests passed with the real-checkpoint test
explicitly excluded; the final failed-state-advance/orphan tests separately
passed 2 tests in 13.51s. Independent final review passed the retry regression
in 6.27s with no additional findings. The Squad integration suite passed
514 tests in 400.80s after correcting the seven obsolete guard expectations;
that run preceded the final recovery corrections, so it is not a final-tree
verification receipt. Broader affected checks passed **798 tests in 275.71s**:
discovery bootstrap/operation/publication/completion, Squad completion/state,
legacy identity exclusion and lock ordering. That run also overlapped the final
normal-entry recovery corrections; the targeted fresh regressions and review
above cover those corrections. These earlier runs are superseded by the fresh
affected verification recorded below after the approved checkpoint extension.

**Original failure, subsequently approved for repair:**
`test_real_checkpoint_policy_completes_before_identity_release`
failed with a real Git repository and checkpoint policy v2. Publication applied,
the existing checkpoint owner creates `specs/game/.echelon/checkpoints.json`,
then the next completion source check rejects that new ledger as source drift.
State remains blocked with pending completion and applied identity publication;
release does not occur. No test is marked xfail or skipped to conceal this.

The existing design pins every spec-tree source through completion, but the
checkpoint owner legitimately writes control metadata inside that tree. This
requires an explicit contract decision, not disabling checkpoints or loosely
ignoring `.echelon`. The extension subsequently approved by the user: keep the current
Git checkpoint flow and ledger location; authenticate exactly checkpoint-owned
metadata against its existing receipt while continuing to pin reviewed artifacts.
Define its relationship to the registered spec source head and subsequent repair
capture, and test checkpoint interruption/tampering before claiming completion.
Do not implement a competing ledger, blindly exclude metadata, update source
heads without bound authority, or alter existing histories.

At that approval pause the checkpoint remained **uncommitted and incomplete**.
Nothing has been installed, activated, migrated, pushed, or run against a live
model or the stopped browser-game workspace.

## Approved checkpoint extension

The user approved the proposed extension in the next turn. Implement inline:

- [x] Keep the Git checkpoint writer and paths unchanged. Add read-only image
  validation to the existing checkpoint owner: the exact completion identity,
  sealed Git parent and receipt determine the one fresh-spec ledger row.
- [x] During the checkpoint step permit only its precise intermediate metadata
  states (private directory, empty private lock, missing or exact ledger).
  Subsequent effects require the exact committed receipt and complete metadata.
  Unknown files, extra rows, changed modes, symlinks or foreign commits block.
- [x] Validate full captured sources, then project only authenticated checkpoint
  metadata out of the spec identity view. The registered head continues to name
  reviewed artifact/graph images, not incidental control metadata. Never alter
  that head outside the existing bound publication owner.
- [x] Preserve checkpoint proof after outbox cleanup in the existing identity
  release payload, retaining the exact completion intent/receipts and marker
  digests. No extra journal. No-checkpoint releases retain their old format.
  Provide a checked captured-spec projection for subsequent source/repair
  admission; this does not by itself activate the deferred repair controller.
- [x] Bind checkpoint target selection to the authenticated spec, not mutable
  state or ambient directories. Keep source validation and read-only checkpoint
  proof outside later completion/checkpoint locks.
- [x] Prove success, interruption before/after Git commit, ledger and receipts,
  tampering, release cleanup/retry and retained projection after cleanup. Run
  affected regressions and independent review, then commit the whole checkpoint.

## Checkpoint extension implementation and review

The existing checkpoint owner computes the exact fresh ledger image without
writing. Its Git proof verifies sealed parent and completion trailers **and** the
complete committed artifact membership, executable modes and raw blob identities.
No text newline normalization is permitted. Once the matching commit exists, the
private directory and empty lock must already exist; the ledger may be absent
only before its receipt. After the receipt all exact metadata is required.

Checkpoint completions retain intent, receipts and marker digests in version 2 of
the existing identity release payload. No-checkpoint version 1 remains unchanged.
The retained proof validator checks the same closed schemas and canonical hashes
as the outbox; the checked projector additionally authenticates the retaining
identity owner, request, history and current source head. It is not a standalone
proof that a caller can self-sign. The full source capture still participates in
the existing read guard.

Independent read-only review reproduced two P2 recovery gaps: receipt lookup after
256 later Git commits, and missing checkpoint locks before receipt. Both have
red/green regressions and fixes. The receipt-selected commit is authenticated
directly while retaining the bounded duplicate check; commit proof requires the
already-created directory and lock. Independent re-review found no remaining
issue in these changes and passed all three regressions in 18.82s.

Fresh verification on the implementation above:

- Real-Git checkpoint tests: **26 passed in 131.52s**, including the original
  successful normal checkpoint, interruptions before checkpoint creation and
  after commit/ledger/receipts, metadata and artifact tampering, old Git history,
  retained-proof integrity, and release/staging cleanup recovery. The original
  normal-entry success case also remains in the normal-entry suite.
- Complete Squad controller integration suite: **514 passed in 383.92s**.
- Broader affected regressions: **1,704 passed in 482.33s**. Scope: discovery
  bootstrap, inputs, operation, turns, semantics, reservations, candidates,
  identity candidate, publication, completion and normal entry; phase checkpoints,
  Squad phase checkpoints/completion/state; legacy identity exclusion and lock
  ordering; Squad source snapshots, publication, publication sources and inspection.
- Total fresh affected checks: **2,244 passed**. `git diff --check` is clean.

The normal-entry/checkpoint integration gate is complete. The next gate remains
accepted-baseline discovery repair, including the original unchanged-ID/evidence
reference regression. Later producer/writer coverage, public selection, real
provider acceptance and installation remain open; this commit does not activate
them. Keep this worktree and branch for continued convergence; no push or merge.

One initial cleanup-interruption test had an invalid fixture assumption:
`last_dispatch` is explicitly null before publication, not an empty dictionary.
Correcting that test reached the intended cleanup boundary; no production change
was needed. The final complete checkpoint run above includes this correction.

No installation, live model call, default activation or stopped-workspace mutation
has occurred.
