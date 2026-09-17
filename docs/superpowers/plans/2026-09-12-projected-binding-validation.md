# Projected binding validation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate evidence and issue requests against proposed lifecycle revisions before publication, using the same binding target rules as final persistence and no database writes.

**Architecture:** Build an internal projected head/revision view from the existing lifecycle planner and one retained read transaction. Let the existing binding target validator read through that view; keep its policy in one place and its normal retained-store path unchanged. Expose a query-only store preflight that returns no receipt or semantic authorization.

**Tech Stack:** Existing SQLite read transactions, lifecycle planner, frozen request types and real-storage pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing Phase A completion transactions, candidate isolation, and repair facilities remain the integration owners.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- IDs travel through interfaces as strings.
- No schema, allocation/import algorithm, lifecycle persistence, binding persistence, provider, controller routing, publication or activation changes in this task.

---

### Task 1: validate bindings against one projected lifecycle snapshot

**Files:** Create `src/harness/element_identity_binding_preview.py` and `tests/unit/test_element_identity_binding_preview.py`; modify `src/harness/element_identity_store.py` for one public read-only wrapper and `src/harness/element_identity_binding_store.py` for a narrow internal target-view hook; document in `docs/element-identity-storage.md`. Do not change lifecycle planner/apply algorithms, candidate rules, binding record/receipt SQL or existing request codecs/types.

**Interfaces:**

```python
# IdentityStore
def validate_projected_bindings(
    self, *, spec_id: str,
    changes: Sequence[lifecycle.LifecycleChange] = (),
    claims: Sequence[bindings.ReferenceClaim] = (),
    occurrences: Sequence[bindings.IssueOccurrence] = (),
) -> None:
    """Validate proposed bindings in one query-only snapshot; no receipt."""

# harness.element_identity_binding_preview
def validate_projected(
    connection, store, spec_id, *, changes=(), claims=(), occurrences=(),
) -> None:
    """Validate on the caller's transaction without owning it or writing."""
```

The three optional batches accept the existing Sequence convention excluding strings/bytes; empty sequences mean no proposed operation of that kind. Snapshot batch membership and revalidate exact immutable types with existing `lifecycle.request` / `bindings.request` when nonempty. Empty str/bytes must not be mistaken for empty batches. Preserve existing per-batch duplicate and lifecycle overlap checks. Validate nonblank/NUL-free UTF-8 spec_id through the existing strict text validator. The public wrapper validates/snapshots before opening one store read transaction, sets `PRAGMA query_only=ON`, invokes the connection-owned helper and returns None. It must not reserve IDs, allocate operation IDs, apply writes/rollbacks as a simulation, persist assessments or produce a receipt. The internal helper requires an active caller transaction, performs only reads and revalidates its inputs; it neither begins/commits/rolls back a transaction nor changes caller PRAGMAs.

For nonempty changes, call the existing `element_identity_lifecycle_store.plan_changes` once within the same read snapshot; its validations remain authoritative for reservations, exact labels, expected heads, subjects, transitions and planned revisions. Empty changes use an empty projection. Do not accept an externally supplied projected-head dict as authority, duplicate lifecycle planning rules, or call a public store method to open another connection. The internal view supplies projected heads for changed labels and falls back to verified retained heads for all others. It supplies a projected revision only when the requested exact label/revision equals that label's planned revision; all earlier revisions still resolve through the retained store validator. Missing future revisions remain missing. Populate kind/ordinal from the planner's new-entity fields or the authenticated retained entity for existing labels; never infer another namespace or latest revision.

Keep the actual binding target policy in `element_identity_binding_store._target`. Extend it with one private optional projected-view argument (default None), or equivalently extract its existing policy once and have retained/projected lookup adapters call it. Do not maintain two policy copies. Default calls from record/read/receipt/audit retain their existing lookup, counter validation, error ordering, returned head, digest and persistence behavior. The projected path uses the same high-water checks, label/kind/ordinal/subject checks, revision-existence checks and exact active historical issue subject/body requirement. A private view contains only the controller's validated planner output and uses the same connection for fallback reads.

Preserve storage semantics, distinct from stricter candidate/current-obligation rules: reference claims may name an existing historical or projected terminal revision; `target_revision=None` stays unassessed and is never upgraded to latest. An issue occurrence must point to an active historical or projected revision with exactly matching subject/title and content/body. It may still point to an earlier active revision when the projected current head retires or supersedes that issue. An occurrence pointing at the new terminal revision rejects. An imported entity permits an unassessed reference but no assessed revision unless an explicit valid adoption is present in the proposed lifecycle batch. This preflight can validate explicit adoption mechanics without authorizing managed candidate adoption or historical reconciliation.

All batches share one coherent projection and one retained transaction, even when claims/occurrences depend on revisions created in the same lifecycle batch. Validate every proposed lifecycle change even if no binding mentions it. Reject the whole preflight on any invalid request, missing/wrong-spec/unreserved target, stale expected revision, immutable subject change, bad transition, missing revision, mismatched issue content or detectable authority damage. Public errors use existing IdentityStoreError normalization, not candidate-repair diagnostics. No partial result or guessed binding escapes; a successful return means only the proposed storage relationships validate in this snapshot, not that source bytes/semantic review/publication are authenticated or that the baseline is reserved after exit.

**First regression before production edits:**

```python
def test_reference_can_validate_against_reserved_projected_creation_without_writes(tmp_path):
    import sqlite3
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_bindings import ReferenceClaim
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Scene body.", "reserve")
    claim = ReferenceClaim("evidence.md", "a" * 64, "span:0:9", label, "1", "evidence")
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        before = tuple(connection.iterdump())
    assert store.validate_projected_bindings(spec_id="demo", changes=(create,), claims=(claim,)) is None
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        assert tuple(connection.iterdump()) == before
    assert store.lookup(spec_id="demo", element_id=label) is None
```

- [ ] Add the regression with `pytestmark = pytest.mark.unit`; run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_binding_preview.py -q` and retain actual missing-store-method RED after real reservation and complete baseline SQL capture.
- [ ] Implement the internal projected view/helper and public query-only wrapper; share the existing binding target policy rather than copy it. Keep all persistence SQL, operation-digest/receipt formats and candidate semantics unchanged.
- [ ] Test all lifecycle variants, all transition kinds, mixed FR/ISS batches, current/older/projected active and terminal target revisions, unassessed references, imported/adopted targets, exact issue title/body including CRLF/Unicode, legacy labels, large revision strings and newly created successors. Assert successful None and full SQL invariance, not only unchanged row counts.
- [ ] Test all malformed/empty/string/duplicate/subclass/damaged-frozen batch variants, wrong spec/reservation, stale heads, changed immutable subjects, future/missing revisions and wrong issue content/status. Include invalid unrelated lifecycle changes in otherwise valid binding batches. Verify before-transaction request rejection and public authority-error normalization; no invalid state is converted into an ordinary repair finding.
- [ ] Exercise the internal helper in a real caller-owned query-only transaction, prove it neither starts another connection nor changes transaction state/PRAGMAs, and reject use without an active transaction. Test injected detectable head/revision/counter damage with full SQL state unchanged from the already-damaged baseline.
- [ ] Compare preflight results to actual existing lifecycle-plus-binding transaction composition: valid projected creation/revision/transition batches subsequently persist through the unchanged connection-owned writers; matching historical/unassessed rules agree. Invalid projected target/content cases also fail final persistence with full caller rollback. Preserve exact original retries after later history in existing compatibility suites; do not create new receipt behavior.
- [ ] Run exactly `tests/unit/test_element_identity_binding_preview.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_transaction_composition.py`, and `tests/unit/test_element_identity_request_codec.py` with the checkout virtualenv once on final code. No full repository, capacity, provider or live run; no unchanged post-commit repeat.
- [ ] Document storage preflight versus semantic/current-obligation/publication authority, self-review shared policy and transaction ownership, run `git diff --check`, commit only task files, and retain full actual command/RED/GREEN output in the report. Root handles plans/ledgers/checkpoints and independent review.

## Remaining integration

This preflight is for the future intent owner's single database snapshot; it does not itself bind source trees, authorize assessed evidence, create an intent/lease or finalize publication. Complete source capture, semantic review, pending-write protection, graph/completion receipts, all managed producers and bounded repair remain required.
