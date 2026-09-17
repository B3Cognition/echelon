# Identity history snapshot implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Supply graph/recovery consumers with one immutable, deterministic observation of a spec's complete materialized identity history, including terminal entities and original evidence bindings.

**Architecture:** Read and audit the existing authority in one caller-owned SQLite snapshot, then serialize the selected spec's retained rows into canonical ASCII JSON. A thin public wrapper owns one query-only transaction; a connection-owned helper supports the existing completion transaction without nested public reads. This is an explicit full-history observation, not an allocator, restore format, graph implementation or semantic certification.

**Tech Stack:** Existing SQLite audit/read validators and canonical JSON/digests, frozen standard-library dataclass, real on-disk transaction tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing Phase A completion transactions, candidate isolation, and repair facilities remain the integration owners.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- IDs travel through interfaces as strings.
- Existing graph keys remain valid.
- Historical evidence is retained, not relabeled as proof of the new content.
- No graph/memory/controller/producer/provider integration, new persistence schema, CLI export/restore command, or activation in this task.

---

### Task 1: capture a canonical materialized-history observation

**Files:** Create `src/harness/element_identity_snapshot.py` and `tests/unit/test_element_identity_snapshot.py`. Modify `src/harness/element_identity_store.py` for one wrapper and the shared namespace helper, `src/harness/element_identity_publication_store.py` solely to use that shared helper, and `docs/element-identity-storage.md`. Do not alter existing lifecycle/binding persistence, audit policy, current schema or allocation algorithms.

**Interfaces:**

```python
# harness.element_identity_snapshot
@dataclass(frozen=True, slots=True)
class IdentityHistorySnapshot:
    payload: str
    sha256: str

def capture(connection, store, spec_id: str) -> IdentityHistorySnapshot: ...

# IdentityStore
def identity_history(self, *, spec_id: str) -> IdentityHistorySnapshot: ...

# Shared connection-only helper, extracted verbatim in behavior from the
# existing publication_store._namespace; works when store is IdentityStore class.
@staticmethod
def _namespace(connection) -> dict: ...
```

Validate `spec_id` using existing exact nonblank/NUL-free UTF-8 `lifecycle.text` before transaction entry, and again inside `capture`. The helper requires an active caller transaction and neither opens/finishes transactions nor changes any PRAGMA. Public wrapper uses one existing `_transaction()` with query_only enabled. Namespace identity comes from validated metadata on that same connection, not an instance `_marker`. Extract the existing namespace validation to `IdentityStore._namespace` and delegate all existing publication uses to it without duplicating that logic or changing validation behavior.

Before constructing output, call the existing full `_audit(connection, lifecycle_state=True, binding_state=True, publication_state=True)` on this exact transaction. Do not audit one connection and read another, skip the publication guard history, build a second looser audit, or catch damage as empty history. Existing `IdentityStoreError` normalization applies to the public wrapper and direct helper. Exact schema validation and namespace checking must occur for the direct helper too, through the shared namespace helper. The whole-authority audit is intentionally explicit and potentially expensive: this observation is not a cheap per-ID lookup, does not change indexed allocation costs, and is not wired into every allocation. Corruption in another spec can fail this full-authority observation. Do not claim per-spec-only audit complexity or million-revision performance.

The snapshot dataclass holds only immutable strings. Its constructor is a value container, not an authorization mechanism; only a returned observation from the validated store capture has the provenance of that call. Consumers must bind it to their own source/intent context and verify the digest. Do not add a general externally supplied history decoder, authority importer or signing system here.

**Exact payload format:** canonical `authority._json` output (sorted object keys, compact separators, ensure_ascii=True). Digest is SHA-256 of these exact ASCII bytes, using the existing canonical digest helper. Root has exactly:

```python
{
    "version": "1", "workspace_uuid": "...", "epoch_uuid": "...", "spec_id": "...",
    "entities": [], "revisions": [], "lineage": [],
    "reference_claims": [], "issue_occurrences": [],
}
```

All records retain exact TEXT/NULL values; no integers, booleans, display renumbering or numeric coercion are introduced. Empty and not-yet-materialized specs return these empty arrays with the actual namespace/spec, not None and not an invented persisted spec record.

- `entities`: one record per selected-spec `entities` row joined to its authenticated head, with exactly `spec_id`, `element_id`, `kind`, `subject`, `ordinal`, `status`, `revision`. Include imported/unassessed, active, retired and superseded entities. Do not materialize unconsumed reservations; omit current content here because exact content is retained in `revisions`.
- `revisions`: every selected-spec row, all exact existing columns: `spec_id`, `element_id`, `revision`, `subject`, `content`, `content_sha256`, `status`, `reason`, `operation_id`. Keep the original operation association and terminal content; do not replace older bodies or hashes with head values.
- `lineage`: every selected-spec row exactly once with all existing columns: `spec_id`, `predecessor_id`, `predecessor_revision`, `successor_id`, `successor_revision`, `kind`, `reason`, `operation_id`.
- `reference_claims`: every selected-spec retained row with all existing columns: `operation_id`, `entry_index`, `spec_id`, `source_path`, `source_sha256`, `source_anchor`, `target_id`, `target_revision`, `relation`, `payload_sha256`. Preserve null/unassessed and older assessed revisions; do not add a current-verification flag or retarget to a head.
- `issue_occurrences`: every selected-spec retained row with all existing columns: `operation_id`, `entry_index`, `spec_id`, `issue_id`, `issue_revision`, `report_id`, `report_sha256`, `display_id`, `title`, `body`, `issue_fingerprint`, `payload_sha256`. Preserve historical occurrence provenance and existing fingerprint bytes.

Order `entities` by `(kind, ordinal is None, len(ordinal or ""), ordinal or "", element_id)` so numeric ordinals are compared by length then digits and opaque labels remain deterministic. This ordering does not reinterpret opaque suffixes. Order revisions by that entity order, then `(len(revision), revision)`. Order lineage by predecessor entity order, successor entity order, then kind and operation_id; each existing pair is unique. Order both binding arrays by `(operation_id, len(entry_index), entry_index)`, preserving original per-operation receipt order; operation IDs themselves are opaque text. Use selected-spec SQL predicates and the existing indexes for retained row selection; do not query public per-element methods opening separate transactions. No fixed-width integer cast or Python global digit-limit change.

Exclude counters, unused reservation rows, general operations/receipt envelopes and publication intent/claim state from this *materialized-history* payload. The existing full backup remains the complete allocation/restore export; this snapshot must not masquerade as a backup. New reservations, prepared intents, release completion data or unrelated-spec mutations cannot change its payload/hash if selected-spec materialized history is unchanged. Applying lifecycle/binding changes must change it; an applied intent's guard can remain pending while this read succeeds. No observer clears a guard or certifies external publication completion. Later mutations do not modify previously returned strings; the snapshot does not promise post-transaction freshness.

**Required first real regression:**

```python
def test_snapshot_retains_old_revision_and_evidence_after_retirement(tmp_path):
    import json
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision, ElementRetirement
    from harness.element_identity_bindings import ReferenceClaim
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Scene", "Original body", "reserve"),))
    store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(
        ReferenceClaim("evidence.md", "a" * 64, "span:0:9", label, "1", "evidence"),))
    store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(
        ElementRevision(label, "1", "Scene", "Revised body"),))
    store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(
        ElementRetirement(label, "2", "No longer an active obligation"),))
    snapshot = store.identity_history(spec_id="demo")
    value = json.loads(snapshot.payload)
    assert value["entities"][0]["status"] == "retired"
    assert [row["revision"] for row in value["revisions"]] == ["1", "2", "3"]
    assert value["revisions"][0]["content"] == "Original body"
    assert value["reference_claims"][0]["target_revision"] == "1"
```

- [ ] Add this unit-marked test and run it using the checkout virtualenv before production changes. Retain actual missing-method RED after real old writers complete, then implement the minimal capture and verify GREEN.
- [ ] Test exact root/record key sets, canonical ASCII bytes/hash, namespace identity, no JSON numeric tokens, empty spec and reservation-only spec, all seven families, unchanged FR-001/composites, numerically ordered 9/10/999999/1000000 and 5,000-digit ordinals/revisions without global interpreter changes. Use real authority-created fixtures; clearly identify any deliberate high-revision SQL fixture and its authentication constraints.
- [ ] Test create/revise/retire/replace/split/merge and imported/unassessed/adopted history, all predecessor/successor links, retained exact source anchors/revisions and null reference bindings, ISS occurrences after later revision/retirement with unchanged original fingerprints. Assert complete rows, not merely record counts.
- [ ] Compare snapshots before/after unrelated-spec work, selected-spec unused reservation, empty publication prepare/apply/release, mixed publication prepare/apply/release, exact retries, restart and backup/restore. Verify selected-spec materialized effects alone change the hash; read does not release prepared/applied guards and original snapshots stay unchanged.
- [ ] Exercise real caller-owned write composition: capture sees the same transaction's uncommitted valid lifecycle/binding rows, does not commit them, and caller rollback leaves the public history unchanged. Public wrapper uses exactly one query-only transaction. SQL trace and full dumps prove no writes/PRAGMA changes/nested transaction in helper. Invalid spec types, subclasses, None, NUL, empty/blank and non-UTF-8 fail before public transaction. Direct helper without transaction fails. Class-based helper works; no instance-only namespace access.
- [ ] Reject detectable schema/counter/head/revision/lineage/binding/publication damage through existing audit, including another spec's damage, without mutation or partial snapshot. Test malformed namespace metadata and metadata/schema mismatch through direct helper. A connection-only helper reads actual validated namespace metadata; its caller remains responsible for associating the connection with the intended filesystem authority marker. Do not claim it can detect a coherently substituted valid namespace without an external expected identity. Do not label hashes cryptographic tamper resistance or evidence assessment.
- [ ] Run once the final covering set: `tests/unit/test_element_identity_snapshot.py`, `tests/unit/test_element_identity_store.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_element_identity_publication.py`, `tests/unit/test_element_identity_transaction_composition.py`, and `tests/integration/test_element_identity_publication.py`. Existing million allocation algorithm case need not repeat because it is unchanged; no full repository/provider/live run or unchanged post-commit rerun.
- [ ] Document exact payload, costs, omitted allocation state and provenance limits. Self-review row completeness/order, namespace extraction and transaction ownership, run `git diff --check`, commit only task files and write full actual RED/GREEN/commands/results report. Root owns plan/ledger/checkpoints and independent review.

## Remaining integration

This phase provides a stable observed history input, not graph lifecycle nodes, consumer freshness gates, semantic approval, historical reconciliation or a typed recovery bundle. The existing graph builder/audit/traversal and memory consumers still require lifecycle-aware adapters preserving exact existing graph keys. Existing completion-owner, provider scope, all producer registration, feature snapshot, bounded repair and final offline/live checkpoints remain required under the approved design. Do not activate a partial set of families or claim this snapshot validates the canonical files.
