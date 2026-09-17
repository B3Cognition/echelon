# Task 1 report: exact proposed materialized identity history

Status: DONE.

Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Branch: `fix/delivery-controller-contract`.
Original base: `5b3442aaeb702d09731712252fe432f0617e5a15`.
Implementation commit: `34f4616b23860d30071c40c5ab685d03c46c1379` —
`feat(identity): preview exact proposed materialized history`.
Exact covering staged tree and implementation commit tree:
`f6af35e69c2fa5f62ab9382e32afb65020cb7092`.

## Implemented interfaces and files

- `src/harness/element_identity_store.py`: adds
  `preview_identity_history(self, *, spec_id: str, operations: tuple[PublicationOperation, ...] = ()) -> IdentityHistorySnapshot`.
  Validates the exact spec ID and detached exact operation tuple before one
  existing `_transaction()`, enables `PRAGMA query_only=ON`, and invokes the
  connection-owned preview. Ordinary exceptions become one fixed bounded
  `IdentityStoreError`, raised after the handler so it retains neither cause nor
  context. `BaseException` and existing transaction cleanup are preserved.
- `src/harness/element_identity_snapshot_preview.py`: new 39-line owner for the
  read-only overlay. Rejects pending same-spec publications and globally used or
  permanently claimed children, captures/audits complete retained history, shares
  the journal plan and binding validation, appends exact planned rows, and updates
  only existing entity head fields. It introduces no lifecycle dispatch policy.
- `src/harness/element_identity_publication.py`: extracts
  `validated_operations` for canonical ordered/unique child validation and
  detached values. Existing publication request validation uses the same helper;
  no dummy parent request, v1/v2 wire change, or weaker frozen-value validation.
- `src/harness/element_identity_publication_store.py`: extracts
  `operation_children`, `planned_effects`, and `require_new_children` from the
  existing journal logic. Existing `_children(request, spec_id)` and `_plan`
  interfaces remain compatible with source-store callers and retained plans.
- `src/harness/element_identity_lifecycle_store.py`: shared pure `revision_row`
  and `lineage_row` constructors used by the existing writer and preview. SQL
  ownership, operation gates, and receipt behavior remain in the existing writer.
- `src/harness/element_identity_binding_store.py`: shared `materialized_row`
  uses existing `_entry`, fingerprint, and binding digest logic; record validation,
  persistence, and preview share its exact row representation.
- `src/harness/element_identity_snapshot.py`: shared `canonical_snapshot`
  preserves version-1 canonical ASCII JSON/hash and exact retained SQL ordering,
  including arbitrary-width decimal strings. Existing retained capture uses it.
- `tests/unit/test_element_identity_snapshot_preview.py`: 60 collected cases
  across 17 test functions, with real authority/journal/graph integration and
  independently specified complete expected rows.
- `docs/element-identity-storage.md`: documents pre-intent inputs, exact byte
  contract, read-only/global claim boundaries, historical binding policy,
  bounded errors, full-audit cost, no lease, and remaining graph/source integration.

No schema, source publication algorithm, state/controller/executor/provider,
startup/CLI, graph/memory production, prose, allocation, or managed-context
checker changes. Root-owned progress remained unstaged and was not committed.

## TDD evidence and focused iterations

All commands below ran from the worktree above, using the existing executable
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`.

Actual first RED, before any production edits:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_snapshot_preview.py
E AttributeError: 'IdentityStore' object has no attribute 'preview_identity_history'
tests/unit/test_element_identity_snapshot_preview.py:10: AttributeError
FAILED tests/unit/test_element_identity_snapshot_preview.py::test_preview_matches_real_journal_application
1 failed in 0.21s
```

Real `IdentityStore.initialize`, reservation, `ElementCreate`, `encode_request`,
and canonical `PublicationOperation` construction all completed before the missing
method failure. Root was notified of this actual RED before production editing.
The first test was subsequently expanded with independent expected complete rows,
canonical payload/hash checks, full before/after SQLite dumps, reopen/release, and
snapshot immutability assertions.

The first implementation run reached the existing source journal during actual
prepare and exposed a compatibility correction:

```text
TypeError: 'PublicationIntentRequest' object is not iterable
src/harness/element_identity_source_store.py:158 called publications._children(request, ...)
1 failed in 0.29s
```

The attempted operation-tuple signature change to `_children` was corrected by
preserving `_children(request, spec_id)` as a wrapper and extracting the new
operation-only `operation_children`. No source-store production edit was needed.

First GREEN:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_snapshot_preview.py
1 passed in 0.26s
```

Subsequent focused module runs, same command, as coverage expanded:

```text
5 passed in 1.82s
57 passed in 4.36s
60 passed in 4.76s
```

The prohibited-path test was then strengthened with an actual SQLite connection
subclass rejecting backup/savepoint/attach/vacuum plus a one-connection assertion:

```text
git diff --check
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_snapshot_preview.py::test_preview_never_calls_writers_source_or_provider_paths
1 passed in 0.24s
```

This test amendment was made before staging the covering code point below.

## Once-only covering verification

Confirmed all nine exact module paths existed before running. Staged only task
implementation/test/docs files, then `git write-tree` returned
`f6af35e69c2fa5f62ab9382e32afb65020cb7092`.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_snapshot_preview.py tests/unit/test_element_identity_snapshot.py tests/unit/test_element_identity_lifecycle.py tests/unit/test_element_identity_bindings.py tests/unit/test_element_identity_binding_preview.py tests/unit/test_element_identity_publication.py tests/unit/test_element_identity_request_codec.py tests/unit/test_spec_graph_identity.py tests/unit/test_element_identity_source_store.py
........................................................................ [ 10%]
........................................................................ [ 21%]
........................................................................ [ 32%]
........................................................................ [ 43%]
........................................................................ [ 54%]
........................................................................ [ 65%]
........................................................................ [ 76%]
........................................................................ [ 87%]
........................................................................ [ 98%]
........                                                                 [100%]
656 passed in 49.56s
```

Exit status 0; no warnings or errors. Source-store coverage was included because
the publication validator/shared helpers changed, covering existing v2/source and
damaged frozen-wire compatibility. The displayed progress lines above combine
the tool's streamed chunks without changing their content.

`git diff --cached --check` passed without output before commit.
The implementation commit's `HEAD^{tree}` exactly equals the covering staged tree.
No production/test/doc amendments followed the covering run. This report is the
only later file addition. No full-unit, controller, capacity, provider, live,
installed CLI, install, or postcommit test run was performed.

## Self-review and acceptance evidence

- Byte equality: independent full expected dictionaries are serialized and hashed
  in test code, then compared to preview and actual journal application. Empty,
  reservation-only, imported, adopted, created, revised, retired, replace/split/
  merge, bindings, and reopen/release paths are covered. Existing retained
  snapshot tests in the covering run protect unchanged wire bytes.
- Historical retention: expected histories accumulate every revision and lineage
  row; immutable entity fields persist through transitions. All seven families,
  opaque/legacy labels, six/seven-digit labels, 5000-digit ordinals/revisions, and
  reference/occurrence indexes 9 through 12 are exercised. Sparse authenticated
  wide-revision fixtures intentionally test accepted historical storage without
  billions of write operations and without changing Python's numeric digit limit.
- Bindings: old evidence keeps the old assessed revision; new assessed references,
  nullable imported/terminal references, projected issue occurrences and exact
  fingerprints are covered. After retirement, new occurrences bound to an older
  active issue revision still succeed. Wrong projected content and a terminal
  revision occurrence fail. No candidate-only active-dependency rule was added.
- Ownership: globally used operation IDs and permanent child claims are rejected
  across specs and across prepared/applied/released states. Pending same-spec
  previews fail even with an empty tuple; retained reads and independent other-
  spec previews remain available.
- Failure atomicity: stale revisions, changed subjects, unreserved/padding aliases,
  missing targets/revisions, malformed payloads, damaged frozen/subclass values,
  duplicate/reordered methods and IDs fail without changing full SQLite dumps.
  A valid existing write succeeds afterward. Other-spec SQL corruption fails the
  full capture audit without modifying data.
- Read-only execution: one traced query-only transaction performs a real attempted
  INSERT inside the lifecycle planner; SQLite rejects it as readonly. Full table
  state is unchanged, no savepoint/attach/vacuum occurs, and later normal writes
  work. Separate tripwires prohibit lifecycle/binding/publication writers,
  operation allocation, source preparation, managed enrollment, backup/restore,
  SQLite backup, extra SQLite connections, and state/provider/controller imports.
- Errors/detachment: ordinary helper/storage exception examples become fixed
  bounded errors with neither cause nor context; `KeyboardInterrupt` and
  `SystemExit` propagate as the identical objects. Input operation mutation after
  transaction entry does not alter detached planning values. Returned snapshots
  remain frozen and their decoded copies are independent.
- Freshness: an intervening legitimate revision stales both the original proposal
  and actual prepare; a fresh valid request using the still-new child ID observes
  the later history. Previously returned payloads and accepted history remain
  unchanged. The test establishes no post-return lease.
- Graph integration: the same real base graph rendered through
  `project_identity_history` and `render_spec_graph` is byte-identical using
  preview or actual applied/reopened/released history. Stable requirement/task
  keys and task status persist. Old evidence targets revision 1 and does not
  acquire an assessment edge to proposed revision 2. No graph write occurs.
- Scope and shared ownership: reviewed staged diffs; lifecycle dispatch, projected
  binding policy, canonical child decoding and SQL writers remain their existing
  owners. The source `_children` compatibility issue was resolved before GREEN.
  No outstanding correctness concern found in self-review.

## Limits and remaining integration

This preview is pre-intent information for new/unclaimed children. It grants no
receipt, recovery, lease, semantic/source authority, runtime activation, or proof
of publication. The v1 test journal requests are caller claims, not physical-source
proof. Complete audit/capture scales with retained authority history.

The graph artifact belongs in the complete source tree and is now computable
before sealing. A trusted captured-source graph builder, semantic/source
authorization, complete staged producer scope, coordinated completion/recovery,
and bounded repair remain future integration. This task does not complete or
activate those paths. Root owns fresh full review against the original base.
