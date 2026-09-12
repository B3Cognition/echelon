### Task 1: preview exact history for new ordered publication operations

**Files:** Create `src/harness/element_identity_snapshot_preview.py` and `tests/unit/test_element_identity_snapshot_preview.py`. Modify `src/harness/element_identity_store.py` for the public entry; `src/harness/element_identity_snapshot.py` for minimal shared canonical encoding/sorting if needed; `src/harness/element_identity_publication.py` and `src/harness/element_identity_publication_store.py` only for narrow shared operation validation/decoding and new-child ownership checks; `src/harness/element_identity_lifecycle_store.py` or `src/harness/element_identity_binding_store.py` only for shared row construction if needed. Existing corresponding tests may gain focused compatibility assertions. Document in `docs/element-identity-storage.md`. Do not change state/controller/executor/provider/startup/CLI production, schema, source publication algorithms, graph/memory production, or prose. Root owns plan/ledger.

**Public interface:**

```python
def preview_identity_history(self, *, spec_id: str,
                             operations: tuple[PublicationOperation, ...] = ()) -> IdentityHistorySnapshot:
    """Observe exact proposed materialized history for new, unclaimed operations."""
```

The return is the existing `IdentityHistorySnapshot` with unchanged canonical version`1` payload and SHA-256. No new wire version or metadata field. For an unchanged accepted database, applying precisely these child operations via the existing publication journal must yield byte-for-byte identical `identity_history(spec_id=...)` payload/hash. The journal's parent/source/release records do not appear in this snapshot, exactly as with retained snapshots. The preview does not contain a fabricated parent/seal/source manifest or evidence of publication.

Validate the independent exact-string spec ID and require an exact tuple of exact `PublicationOperation` records. Reuse the existing canonical payload codec and exact ordered unique method/operation constraints: lifecycle, reference_claims, issue_occurrences, each at most once in that order. Empty tuple is valid. Extract that validation from the existing publication request validator if needed and use it in both callers; do not invent a dummy PublicationIntentRequest with fake hashes/recovery text to reuse it. Detach immutable operation values before transaction use and revalidate damaged frozen instances/subclasses, bad fields, malformed payloads, duplicate/reordered methods or operation IDs. Do not relax existing v1/v2 wire validation.

Use one existing `self._transaction()` with `PRAGMA query_only=ON`. The proposed operations must be new: reject any operation ID already present in global operations or permanently claimed by a publication child, including claims/operations belonging to another spec. Reuse a narrow helper extracted from the existing journal prepare loop if needed. Reject a pending publication for this spec, including when the proposed tuple is empty; the existing retained-history read remains available during pending state. These restrictions distinguish this pre-intent preview from recovery or old-operation retry. No operation row, reservation, claim or pending intent is inserted or deleted, including on failure. Do not call `_operation`, lifecycle/binding writers, SQL savepoints, SQLite backup/copy, or a write connection to simulate application. A later fresh preview of the same still-new operations may observe a changed baseline; it has no retained receipt. Actual prepare remains responsible for the parent operation ID, new claims, baseline/CAS and later recovery.

Capture existing complete retained history using the same full-audit snapshot owner on that transaction. Reuse `lifecycle_store.plan_changes` and the existing projected binding validation to validate all proposed lifecycle/ref/issue effects together. Keep the existing lifecycle subject/status/revision/counter rules, alias checks, active/current versus historical issue occurrence rules and unassessed None bindings. No semantically assessed history is inferred from import. Request decoding and planning must share the existing journal's rules, not copy another switch over lifecycle types.

Overlay only the resulting planned rows and validated binding rows on detached retained data:

- Every old entity, content revision, lineage row, reference claim and issue occurrence remains exactly present, including terminal and imported/unassessed data.
- Creates add an entity with its reserved exact label/kind/ordinal/subject and planned head. Existing changes update only status/revision in the entity record; immutable subject/kind/ordinal/label remain untouched.
- Append planned revision rows with exact existing writer fields, reason/None semantics, operation ID and UTF-8 content SHA. Append exact planned lineage rows with the selected lifecycle child operation ID. Reuse small pure row constructors in the existing writer if this avoids duplicated serialization; keep the SQL owner and receipt/retry behavior unchanged.
- Reference and occurrence rows use their own selected child operation ID, decimal-string one-based entry_index, exact existing payload, existing issue fingerprint and existing `payload_sha256` binding formula. Reuse binding `_entry` and digest construction or a small shared pure constructor; do not independently reinterpret reference/occurrence authority.
- Canonical ordering must exactly match retained snapshot SQL ordering: entity kind, known ordinal before None, ordinal length/value, then exact label; revisions additionally revision length/value; lineage predecessor entity order then successor entity order then kind/operation; bindings operation_id then entry-index length/value. Preserve all string/null types. Do not convert arbitrary-width ordinals/revisions to bounded integers or sort their numeric value lexicographically without length. Refactor only necessary canonical construction; existing retained snapshot bytes must remain unchanged.

The public entry rejects ordinary malformed input/helper/storage failures as a fixed bounded `IdentityStoreError` after the exception handler, with no retained cause/context; preserve BaseException and query-only cleanup. No file/source/state access beyond existing authority operations. Full history capture/audit intentionally scales with retained history and is not advertised as cheap per-ID lookup; no whole-ledger scan is added to allocation or the managed-context checker. Calling preview does not certify rendered Markdown, graph source rows, namespaces selected by a future owner, evidence semantics, publication freshness or missing runtime metadata.

**Required first actual regression before production:**

```python
def test_preview_matches_real_journal_application(tmp_path):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_publication import PublicationOperation, PublicationIntentRequest
    from harness.element_identity_request_codec import encode_request
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    changes = (ElementCreate(label, "Scene", "Initial scene", "reserve"),)
    operation = PublicationOperation("lifecycle", "create", encode_request("lifecycle", changes))
    proposed = store.preview_identity_history(spec_id="demo", operations=(operation,))
    store.prepare_identity_publication(spec_id="demo", operation_id="publication",
        request=PublicationIntentRequest("a" * 64, "test recovery", (operation,)))
    store.apply_identity_publication(spec_id="demo", operation_id="publication")
    assert proposed == store.identity_history(spec_id="demo")
```

Actual initialization/reservation and existing operation validation must succeed before AttributeError for the missing preview method. The test's existing v1 journal request is a test caller claim, not physical-source proof. Notify root of actual RED before production. Expand this first test with independent expected complete rows and before/after database state assertions, rather than relying only on two implementations agreeing.

- [ ] Obtain actual first RED, implement the smallest shared validation/plan/overlay/canonical path and make it GREEN. Use the existing pytest executable from this worktree; no provider or installed CLI.
- [ ] Add independently specified complete expected rows and exact payload/hash checks for empty/reservation-only/imported histories, all seven families, mixed preserved legacy/opaque and six-/seven-plus-digit labels, wide numeric revision/ordinal ordering and binding entry indexes crossing9/10. Existing snapshots and preview inputs remain immutable/detached.
- [ ] Exercise Create, Adopt, Revise, Retire and replace/split/merge lineage on real stored baselines. Include old evidence bound to old revisions, new assessed and None/unassessed refs, historical active issue occurrences after retirement, and new projected issue occurrences with exact fingerprints. Compare full preview to actual journal application, reopen and release—not counts or selected IDs only. No unassessed import becomes assessed unless an explicit valid Adopt is in the plan.
- [ ] Verify failed stale-revision, changed subject, unreserved/padding alias, invalid target/revision, wrong projected occurrence and malformed or conflicting child operation requests reject under the existing planners with no DB rows/counters/claims changed. Preserve their accepted historical/None binding semantics; candidate-only active-dependency policy remains in the existing candidate checker, not a new rule here. Exact prior operations and permanent claims across specs are rejected, not replayed; pending same-spec preview rejects, other-spec independent preview remains possible. After failed preview, normal valid existing writes still work and connection/lock state is released.
- [ ] Prove one query-only transaction with an actual attempted SQL write inside an instrumented planning helper; it must fail and leave state unchanged. Prohibit calls to writers, savepoints, backup/copy and state/source/provider APIs with scoped tripwires. Add ordinary error/context and identical BaseException propagation cases.
- [ ] Verify before-return snapshots do not reserve a baseline: a legitimate later revision makes the old proposal stale; a fresh valid request previews new history. Neither the old payload nor any accepted history is rewritten. No concurrency test should claim a post-return lease.
- [ ] Add a real existing graph projection/rendering integration case using `project_identity_history` and `render_spec_graph`: the same base graph rendered with preview equals rendering with actual journal-applied history byte-for-byte, stable req/task keys remain unchanged, and old evidence edges still target the old revision rather than certify the newly proposed one. No graph production change or canonical graph write.
- [ ] Run the covering set once: `tests/unit/test_element_identity_snapshot_preview.py`, `tests/unit/test_element_identity_snapshot.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_element_identity_binding_preview.py`, `tests/unit/test_element_identity_publication.py`, `tests/unit/test_element_identity_request_codec.py`, `tests/unit/test_spec_graph_identity.py`, and `tests/unit/test_element_identity_source_store.py` if the publication validator/shared helper is changed (it exercises v2/frozen wire compatibility). Verify exact existing test names before running. No full-unit/controller/capacity/live/install or postcommit repeats. Report staged/commit code points for any later amendment and its focused evidence.
- [ ] Self-review byte equality, historical retention, shared validation/row construction, pending/global claim boundaries and honest pre-intent limits; document/diffcheck/commit task files and full report. Root owns fresh full original-base review after DONE.

## Remaining integration

The existing source tree includes `spec-artifact-graph.json`; this preview lets a later trusted owner compute that artifact before sealing instead of mutating it after guarded publication. A captured-source graph builder, semantic/source authorization, complete staged producer scope, coordinated completion/recovery and bounded repair still need integration. This phase enables none of those paths and is not their completion.
