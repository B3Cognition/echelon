# Reviewed discovery publication preparation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, as requested by the user. Use test-driven development and independent read-only review.

**Goal:** Turn an existing accepted discovery operation into a sealed spec/graph publication package, without promoting sources or claiming controller completion.

**Architecture:** Replay the existing checked operation; never accept a caller-supplied candidate as semantic authority. Use existing Squad publication transactions to seal source outputs, derive the graph from projected bytes/history, and seal the final source-plus-graph stage. Keep the registered spec-only identity source baseline separate from the complete publication read set. Return a version-3 identity request and its bound full read set for later authenticated completion association.

**Tech Stack:** Python, existing receipt-backed discovery, Squad publication/source snapshots, captured graph assembly, identity v3 requests, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`

## Global constraints

- Continue in the existing `fix/delivery-controller-contract` worktree. No installation, migration, live model calls, public activation, push or merge.
- No new publication/completion engine, identity authority, provider adapter, prose, AGENTS.md/CLAUDE.md or legacy build changes.
- Caller owns Phase A/run execution leases. Preparation requires an already accepted operation and checked reply replay; it cannot start a producer or repair attempt.
- Canonical bytes, identity history/source heads and pending Squad completion/publication markers remain unchanged.
- The existing registration fixes its spec-only source selection. Do not widen it to runtime inputs or replace genesis. Full runtime read-set preservation belongs to the guarded publication snapshot, not the accepted-spec source head.
- Missing or changed receipts/inputs block. Unbound staging can be prepared again with fresh transaction IDs, without a new reservation or provider call; no pending publication may be discarded or reselected.
- This checkpoint is the preparation part of publication/completion integration. Persisted association, guarded promotion/application, completion/release and positive Squad recovery remain open. Returned hashes/recovery payloads do not authorize them.

## Task 1: Prepare the sealed reviewed source/graph package

**Files:** Create `src/harness/discovery_publication.py`, `tests/unit/test_discovery_publication.py`; extend the private capture result in `src/harness/discovery_operation.py` to expose its detached sources after normal inspection exit.

**Necessary replay guard:** Thread a host-only `replay_only` check through the
existing operation, provider-step and reservation-binding owners. An accepted
operation must have all completed receipts; preparation cannot reconstruct a
missing proposal/reservation or append a provider step. Ordinary execution and
its existing interrupted-turn recovery remain unchanged. The regression tests
first reproduced missing provider steps and reconstruction of missing/incomplete
reservation receipts. No adapter, provider prose or new execution owner is added.

**Interface:** `prepare_discovery_publication(project_root, state_store, executor, *, completion_id)` returns a `PreparedDiscoveryPublication` with `publication`, `sources` (complete original read set), `request` (spec-only v3 source claim), `candidate`, and `graph` bytes. It takes no candidate or caller-supplied read set. Preparation errors are bounded `ValueError`s. The supplied completion ID is a proposed association only, not proof of a pending completion.

- [x] Write the consumer test with a real reviewed operation and real staging/SQLite; assert only selected spec outputs plus graph are staged, no canonical mutation, and no additional model calls.

```python
reviewed = execute(prepared, executor, create=True)
package = prepare(prepared, executor, completion_id="a" * 32)
assert {op.target for op in package.sources.publication.operations} == {
    "specs/game/unknowns.md", "specs/game/assumptions.md", "specs/game/spec-artifact-graph.json"}
assert package.request.proposed_history_sha256 == reviewed.candidate.history.sha256
assert len(executor.calls) == 3
```

- [x] Run red before implementing the missing module. Add failures for no accepted operation, malformed completion ID, changed/deleted receipts, changed runtime/spec/role inputs, pending publication, and tampered stages.
- [x] Implement receipt replay and source revalidation. Seal a provisional source-only transaction using exact UTF-8 bytes and retained target modes, project it using the existing source projection owner, and derive the graph from proposed identity history.
- [x] Seal final source/graph output. Check the source manifests match the reviewed capture, graph bytes match final projected images, and a fresh operation capture still has the selected fingerprint. Preserve runtime inputs as read-only dependencies, not writes.
- [x] Construct the v3 request with a spec-only baseline matching the managed source head and a recovery document binding proposed completion ID, operation/candidate/review, full source snapshot, and projected graph. The absent-memory observation must say unavailable/not configured, never a successful external audit; derive this only after real runtime input admission, with no memory query or collector.
- [x] Test that the existing identity publication preparer accepts the registered spec-only source claim while `publish_sources` would guard the full original read set. Use temporary test authority only; no production promotion or completion calls are introduced.

## Task 2: Faults, review and checkpoint

- [x] Inject source/config drift during staging/graph construction, missing stages and retry after a preparation interruption. Assert no provider redispatch, no identity application and no pending completion authority.
- [x] Run discovery/source/projection/graph/publication and completion/state regressions. Independently review the completed implementation while tests run; correct substantive findings with regressions.
- [x] Update this plan, the convergence boundary and deferred register with exact evidence and remaining completion/recovery work.
- [x] Check the diff, commit the checkpoint and retain branch/worktree; no merge or push.

## Evidence and remaining boundary

Baseline: **58 operation and graph/publication composition tests passed in
49.91s** at `420376aa`. The first 17 preparation cases failed on the absent
module. The two replay-only tests failed on the absent mode; subsequent
missing/incomplete reservation cases reproduced receipt reconstruction despite
requesting replay-only. The completed initial batch passed **21 tests in 27.47s**.

Fault coverage adds changed config/input/roles/receipts during graph construction,
changed/deleted final stage images, interruption after final sealing and checked
retry of a two-attempt operation. A real same-subject repair preserves its `0640`
target mode, proposes revision 2 and leaves revision 1 canonical until promotion.
The graph exposes memory status `unavailable` through its existing audit input;
there is no new graph serialization field or external audit invocation.

Successful preparation discards only its own provisional stage via the existing
publication owner. A preparation failure or process interruption may leave
unbound staging; retry selects fresh IDs, never adopts or erases another pending
transaction. No cleanup scanner or reset protocol is introduced.

The production completion association, guarded source promotion/identity
application, durable completion effects/release and recovery ordering remain
unimplemented here. The full read set in the proposed request must survive that
association; its spec-only baseline must not be used as a substitute guard.
Subsequent accepted repair selection must account for the existing derived graph
without treating it as editable producer prose. Positive Squad entry and all
broader domain/producer/rollout duties remain in the convergence record.

Affected verification: **2,991 tests passed in 186.83s**. The 34-case preparation
suite then passed in **49.52s**, including three newly added pending-Squad and
phase/status exclusion cases. One additional final-graph mismatch regression
passed in **1.82s** (35 preparation cases total). An existing reservation
interruption fixture was updated to forward the new keyword argument; its
interruption and normal recovery remain exercised in the affected suite.
These are offline component/owner tests, not live-provider or positive Squad
admission acceptance. Exact affected command:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest \
  tests/unit/test_discovery*.py tests/unit/test_element_identity_candidate*.py \
  tests/unit/test_element_identity_legacy_guard.py tests/unit/test_element_identity_publication*.py \
  tests/unit/test_squad_source*.py tests/unit/test_squad_publication*.py \
  tests/unit/test_identity_graph_publication_composition.py tests/unit/test_spec_graph*.py \
  tests/unit/test_controller_lock_order.py tests/unit/test_squad_completion.py \
  tests/unit/test_durable*.py tests/unit/test_inspection*.py \
  tests/unit/test_host_serviced_inspection.py tests/kernel/test_squad_state.py -q --tb=short
```

Independent review reproduced a missing binding between intended writes and the
sealed postimages: modification before `add_write` was self-consistent to the
publisher and could escape graph comparison, especially because the graph
correctly ignores its own output. Four content/mode regressions for prose and
graph failed before correction, then passed in **6.20s**. All three publication
inspections now require the exact expected target/action/bytes/mode set and zero
promotion prefix, in addition to the unchanged complete source manifest.

Review also reproduced unnecessary replacement of the completed provider receipt
file during replay. A real inode/mtime regression failed first. Replay-only now
checks limits in detached values without rewriting the receipt; ordinary resume
continues to persist tightened limits. No provider or reservation behavior changed.

Independent re-review confirmed both corrections and passed the complete
**40-case preparation suite in 59.82s**. No outstanding Critical or Important
issues remain. The reviewed implementation remains inactive; all actual
publication/application in tests uses explicit temporary fixture authority.

Final affected run after both review corrections: **3,000 tests passed in
197.06s**, using the command above and including all 40 preparation cases.
Whitespace checks passed. Checkpoint retains `fix/delivery-controller-contract`
and its existing worktree; no installation, migration, live provider calls,
positive runtime activation, push or merge.
