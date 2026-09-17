# Publication history binding implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Bind an identity publication to the exact complete proposed materialized-history fingerprint used to render its graph, rejecting unrelated intervening history changes before acceptance.

**Architecture:** Add an opt-in history claim to the existing publication request and application receipt. Reuse the reviewed full-history capture, pure overlay and sole journal writers inside the existing transaction. Keep legacy requests byte-identical and keep runtime activation off.

**Tech Stack:** Python frozen request DTOs, canonical JSON, existing SQLite publication transaction, materialized snapshots and graph projection.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- Publication uses a durable intent and idempotent receipt integrated with existing completion transactions.
- A pending publication blocks conflicting writes until reconciled.
- This task changes an opt-in journal contract, not a live producer, semantic reviewer, source selector, graph publisher, completion owner or runtime mode.
- Preserve existing request v1/v2 bytes, snapshot v1 bytes, schema6 layout, marker/user_version1, sole transaction/writer ownership, exact old-operation retry and indexed common allocation/source-context checks.

---

### Task 1: bind and enforce the complete proposed history digest

**Files:** Modify `src/harness/element_identity_publication.py`, `src/harness/element_identity_publication_store.py`, `src/harness/element_identity_source_store.py` for request/application envelope compatibility, and `src/harness/element_identity_snapshot_preview.py` for a minimal shared pure overlay extraction. Modify `src/harness/element_identity_snapshot.py` only if a necessary narrow shared row-capture boundary cannot otherwise be reused. Create `tests/unit/test_element_identity_publication_history.py`. Existing publication/source/snapshot tests may gain narrowly needed compatibility assertions. Document in `docs/element-identity-storage.md`. No database/schema/admin/state/controller/executor/provider/CLI/startup/graph/memory production or prose changes. Root owns plan and ledger.

**Interface:** Append `proposed_history_sha256: str | None = None` to the existing frozen `PublicationIntentRequest`, after `sources`. All old positional/default call sites keep their meaning. Non-None is an exact lowercase SHA-256 string validated with the existing hash validator, not a snapshot object, numeric coercion or caller-selected fallback.

Encoding without the new claim remains byte-for-byte existing v1 (no sources) or v2 (with sources). With the claim, emit canonical version`3`, existing root fields plus mandatory `proposed_history_sha256`, and `sources` only when non-None. Decoding accepts precisely two closed v3 shapes (with or without the complete existing source claim); explicit null/missing history, explicit null sources, extra keys, malformed values, duplicate JSON keys and damaged frozen instances reject. v1/v2 with the new key reject. Keep all request operation ordering/canonical payload and source marker rules. Strict decoding grants no authority. No database migration: this is a versioned payload stored in unchanged columns. Older binaries must reject unsupported v3 on interpretation; matching code remains a rollout requirement.

For a new history-bound prepare, derive the exact proposed snapshot from the actual accepted database and the detached ordered operations inside the existing write transaction **before inserting the parent, claims or source plan**. Reuse the reviewed snapshot-preview planner/capture/overlay, not a second lifecycle/binding implementation. Compare its SHA to the request claim; mismatch fails with no DB mutation. A concurrent change to an unrelated entity, reference claim or occurrence in the same spec must invalidate a previously computed complete graph history, even when the proposed operations still validate by themselves and the source head did not advance. Namespace and spec are already in the snapshot digest. Changes to unused reservations alone or other specs do not change this spec's materialized history and must not cause false rejection. Existing/new-child and pending guards remain.

Exact prior preparation retries must still load and compare the retained request and return the original preparation before attempting a fresh preview. Changing only the history claim under the same parent operation ID is a conflicting retry. Empty-operation history-bound publications are valid. The request hash already binds the history claim; preparation and release receipt formats remain unchanged.

Before applying a still-prepared history-bound publication, after `_load` validates its retained parent/plan/claims, recheck that overlaying its exact operations on current complete retained history yields the claimed SHA. The public pre-intent preview still rejects pending publications: do not weaken it or add a general pending bypass. Extract a small private pure `overlay` over a detached retained snapshot, already decoded children and existing planned rows if needed, and reuse it from the preview and this validated prepared owner. Full capture can run here because `_load` itself does not recursively capture history. Do not put whole-history scans in `_load(effects=False)`, the common child/allocator guard, source/managed context reads or `_application` receipt reconstruction. A prepared read remains a retained-intent observation, not a new complete-history freshness check.

Apply through the existing sole child writers. A history-bound application receipt uses version`3` and adds `identity_history_sha256` equal to the retained request's `proposed_history_sha256`; optional `sources` retains its exact existing receipt. Preserve complete operations and publication fields. After child effects, source acceptance and the existing parent applied-state/receipt update, capture actual complete materialized history inside the same uncommitted transaction and compare its SHA to the claim. Any mismatch or ordinary failure rolls back all child rows, source-head changes and parent application state. No second transaction, savepoint, in-memory database copy, graph/file write or callback side effect. The receipt is not returned as successful before this check.

Retained application reconstruction and source `_parent`/`_bound_row`/`accept` checks must enforce the closed version3 envelope and exact request/history association without recapturing today's history. Extract narrow shared pure receipt-version/metadata rules if needed to avoid divergent v1/v2/v3 switches. Read, exact prepare/apply/release retry, reopen, backup/restore and full audit after later accepted history must preserve the original application digest and original history claim—not compare an old released receipt to the latest snapshot or rewrite it. Rehashed request-only or receipt-only history tampering must reject where the retained request/receipt/operation digest associations disagree; coherent malicious rewrite of every authority row is not cryptographic tamper-proofing.

This checks materialized-history equality, not that a supplied graph was actually rendered from it. It authenticates neither complete physical source selection nor semantics, runtime selection, historical adoption or graph artifact bytes. The future trusted graph/source/completion owner must bind those separately. Full-history work is intentionally expensive per publication; no millions-of-writes throughput claim or per-ID scan is introduced. No live caller supplies the new field in this task.

**First actual RED before production:**

```python
def test_history_bound_publication_retains_exact_snapshot(tmp_path):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_publication import PublicationOperation, PublicationIntentRequest
    from harness.element_identity_request_codec import encode_request
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    changes = (ElementCreate(label, "Scene", "Initial scene", "reserve"),)
    operation = PublicationOperation("lifecycle", "create", encode_request("lifecycle", changes))
    proposed = store.preview_identity_history(spec_id="demo", operations=(operation,))
    request = PublicationIntentRequest("a" * 64, "test recovery", (operation,),
                                       proposed_history_sha256=proposed.sha256)
    store.prepare_identity_publication(spec_id="demo", operation_id="publication", request=request)
    receipt = store.apply_identity_publication(spec_id="demo", operation_id="publication")
    assert receipt["version"] == "3"
    assert receipt["identity_history_sha256"] == proposed.sha256
    assert store.identity_history(spec_id="demo") == proposed
```

Initialization, real reservation, canonical child request and existing preview must succeed before TypeError for the new keyword. Notify root of actual RED before production. The fake seal hash is a journal-only test claim, not physical publication proof.

- [ ] Write/run the first actual regression, implement the smallest shared request/overlay/journal path, and obtain GREEN. Use `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest` from this worktree, and `PYTHONPATH=src` for standalone Python.
- [ ] Add independent literal v1/v2/v3 wire and receipt expectations, both v3 source variants, empty operations, all child methods, exact strings/detachment and malformed closed-shape checks. Do not rely only on encode/decode roundtrips agreeing.
- [ ] Demonstrate stale proposed history after a real legitimate unrelated entity revision and after real added reference/issue rows: the child proposal remains valid but bound prepare rejects without rows/claims/counters/source changes. Fresh recomputed SHA succeeds. Other-spec changes and unused reservations preserve the expected digest. Include wide labels and old evidence targeting an earlier revision.
- [ ] Verify prepared ownership still blocks ordinary conflicting writes and public preview still rejects pending state. Inject a coherent unrelated materialized-history change as an explicit corruption/fault fixture to exercise pre-apply whole-history recheck; it must not run child writers or clear the pending intent. Do not describe a raw-SQL fixture as an allowed concurrent writer.
- [ ] Inject a faulty child writer that produces extra otherwise internally consistent history after the precheck: the post-application whole-history check must fail and rollback every affected row/source/receipt. Exercise actual SQL pre-commit failure and post-commit uncertainty/reopen using existing test patterns; retries must neither duplicate child effects nor lose the original claim.
- [ ] Use actual source capture/seal/source registration with a v3 source-bearing request and real guarded publication to verify accepted source/head/application hashes and recovery remain consistent. Cover prepare/apply/release, restart, exact retry after later history, malformed/changed request and receipt associations, and backup/restore with original receipt retention. No installed CLI/provider or stopped workspace.
- [ ] Test real existing graph projection/rendering from the proposed snapshot against applied history, retaining stable entity keys and old evidence revision bindings. This is byte-equality evidence, not graph-source authentication.
- [ ] Ensure source/managed-context read and common allocator checks stay indexed using existing authorizer/tripwire patterns; no full-history call is introduced in them. Keep old full-audit semantics and no recursive capture. Document exact cost and limitations.
- [ ] Run once the complete covering modules: `test_element_identity_publication_history.py`, `test_element_identity_publication.py`, `test_element_identity_source_store.py`, `test_element_identity_snapshot_preview.py`, `test_element_identity_snapshot.py`, `test_element_identity_managed_context.py`, `test_element_identity_request_codec.py`, `test_spec_graph_identity.py` under `tests/unit/`. No full-unit, capacity, live/controller/global installation or unchanged postcommit repeat. Later amendments get named focused coverage with precise code/test chronology.
- [ ] Self-review compatibility, new/apply/retry ordering, complete rollback, source envelope association and no-scan boundaries; document, diff-check and commit task files plus full report. Root owns fresh original-BASE review after DONE.

## Remaining integration

Captured-source graph construction, managed runtime selection, all producer proposals/reservations, semantic authorization, coordinated completion/recovery, lifecycle-aware memory and bounded repair remain separate integration work. This checkpoint prevents a stale complete-history plan from becoming an accepted bound journal publication; it does not activate those consumers.
