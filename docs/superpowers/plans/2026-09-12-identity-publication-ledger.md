# Identity publication ledger implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Retain a publication's exact identity requests, block conflicting ledger writes across restart, atomically apply its lifecycle/binding operations once, and retain the guard until the existing completion owner explicitly records reconciliation evidence.

**Architecture:** Add an explicit schema-4 publication journal to the existing SQLite authority. A prepared record owns globally claimed child operation IDs and one spec-wide pending slot; an applied record retains immutable child receipts but still owns that slot; release records caller-supplied completion evidence and retains all history. Existing connection-owned writers and the common operation gate remain the only identity persistence path. This is inactive storage machinery, not a new workflow controller or proof that files/semantic review/graphs were authenticated.

**Tech Stack:** Standard-library SQLite, existing request codecs/planners/writers, strict immutable requests, real on-disk/process tests and frozen older DDL.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing Phase A completion transactions, candidate isolation, and repair facilities remain the integration owners.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- IDs travel through interfaces as strings.
- A pending publication blocks conflicting writes until reconciled.
- No provider, candidate/semantic authorization, controller routing, filesystem publication, graph projection, completion-owner or activation integration in this task. Do not add a release/cancel command to the administration CLI.

---

### Task 1: persist, guard, apply and reconcile an identity publication batch

**Files:** Create `src/harness/element_identity_publication.py` for request validation/codec, `src/harness/element_identity_publication_store.py` for caller-connection journal/guard/audit operations, `tests/unit/test_element_identity_publication.py`, `tests/integration/test_element_identity_publication.py`, and `tests/fixtures/element_identity/authority-v3.sql`. Modify `src/harness/element_identity_store.py` for wrappers/common gate/audit dispatch and `src/harness/element_identity_schema.py` for exact additive schema-4 migration. Modify current-version expectations/older-schema fixtures in `tests/unit/test_element_identity_admin.py` and `tests/unit/test_element_identity_bindings.py` without removing prior assertions. Document in `docs/element-identity-storage.md`. Existing lifecycle/binding SQL and receipt formats remain unchanged. If sharing the existing codec's strict string-tree JSON parser is needed, extract it into `src/harness/element_identity_json.py` and delegate from `element_identity_request_codec.py`; retain all existing codec behavior and error normalization, rather than maintaining two decoder policies.

**Request interfaces (`harness.element_identity_publication`):**

```python
@dataclass(frozen=True, slots=True)
class PublicationOperation:
    method: str
    operation_id: str
    payload: str

@dataclass(frozen=True, slots=True)
class PublicationIntentRequest:
    manifest_sha256: str
    recovery_payload: str
    operations: tuple[PublicationOperation, ...] = ()

def encode_publication_request(request: PublicationIntentRequest) -> str: ...
def decode_publication_request(payload: str) -> PublicationIntentRequest: ...
```

These are exact frozen types, revalidated on every public/internal boundary to reject subclasses and modified frozen objects. Method is one of `lifecycle`, `reference_claims`, `issue_occurrences`; each occurs at most once, in that order (subsets and an empty operations tuple are valid). Child operation IDs are exact nonblank/NUL-free UTF-8 strings, unique and different from the parent ID. Each payload must be exactly the canonical ASCII output of the existing `encode_request(method, decode_request(method, payload))`; no numeric coercion, alternate whitespace serialization, guessed method or arbitrary class construction. Manifest hash uses the existing exact lowercase SHA validator. Recovery payload is an exact nonblank/NUL-free UTF-8 string retained without normalization. It is opaque controller-owned recovery data: storage binds its exact content but does not parse or certify source coverage, original preimages, semantic judgments or filesystem paths. The future completion owner must supply and authenticate the complete versioned recovery bundle, not a provider assertion.

Encode canonical ASCII JSON with exact keys `version`, `manifest_sha256`, `recovery_payload`, `operations`; version is string `"1"`. Each operation object has exactly `method`, `operation_id`, `payload`. Decode only this closed shape, duplicate-key-free at every level; reject numeric tokens/nonfinite constants, booleans/null in required fields, non-UTF-8 strings, unexpected keys, unknown versions and malformed/deep inputs with a bounded `PublicationIntentError(ValueError)`. IDs/revisions inside existing method payloads remain strings, including arbitrarily wide decimals and exact legacy labels. Do not treat decoding as execution or adoption authorization.

**Store and connection-owned interfaces:**

```python
# IdentityStore; write wrappers validate/snapshot before one write transaction.
def prepare_identity_publication(self, *, spec_id: str, operation_id: str,
                                request: PublicationIntentRequest) -> dict: ...
def apply_identity_publication(self, *, spec_id: str, operation_id: str) -> dict: ...
def release_identity_publication(self, *, spec_id: str, operation_id: str,
                                completion_payload: str) -> dict: ...
def identity_publication(self, *, spec_id: str, operation_id: str) -> dict | None: ...
def pending_identity_publication(self, *, spec_id: str) -> dict | None: ...

# element_identity_publication_store; all require an active caller transaction,
# revalidate inputs, and neither begin/commit/rollback nor change PRAGMAs.
def prepare(connection, store, spec_id, operation_id, request) -> dict: ...
def apply(connection, store, spec_id, operation_id) -> dict: ...
def release(connection, store, spec_id, operation_id, completion_payload) -> dict: ...
def read(connection, store, spec_id, operation_id) -> dict | None: ...
def pending(connection, store, spec_id) -> dict | None: ...
def audit(connection, store) -> None: ...
```

Read wrappers use one query-only transaction. Validate spec_id and parent operation_id with the existing strict nonblank/NUL-free UTF-8 text validator, without normalization. All public authority failures normalize to IdentityStoreError, not repair diagnostics or successful partial receipts. Missing intent lookup returns None; an existing ID belonging to another spec/method fails, not an invented empty record. Apply/release require an existing exact intent. No filesystem I/O, provider work, lock acquisition, timeouts, counter allocation/import, or automatic cancellation in these helpers. Their caller remains responsible for authenticating the sealed/current files under the existing lock before application, and required graph/completion evidence before release. Calling release in an inspection body before normal-exit verification is not a valid integration.

**Schema and retained formats:** Freeze today's entire schema as `SCHEMA_V3`, retaining frozen v1/v2 unchanged; schema version becomes string `"4"`, while marker/user_version stay format 1. Add only these objects (canonical DDL may concatenate literals in local style):

```sql
CREATE TABLE publication_intents (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), spec_id TEXT NOT NULL, request TEXT NOT NULL, request_sha256 TEXT NOT NULL, plan TEXT NOT NULL, plan_sha256 TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('prepared','applied','released')), application_receipt TEXT, application_receipt_sha256 TEXT, completion_payload TEXT, completion_payload_sha256 TEXT, CHECK ((state='prepared' AND application_receipt IS NULL AND application_receipt_sha256 IS NULL AND completion_payload IS NULL AND completion_payload_sha256 IS NULL) OR (state='applied' AND application_receipt IS NOT NULL AND application_receipt_sha256 IS NOT NULL AND completion_payload IS NULL AND completion_payload_sha256 IS NULL) OR (state='released' AND application_receipt IS NOT NULL AND application_receipt_sha256 IS NOT NULL AND completion_payload IS NOT NULL AND completion_payload_sha256 IS NOT NULL))) WITHOUT ROWID;
CREATE UNIQUE INDEX publication_pending_specs ON publication_intents (spec_id) WHERE state!='released';
CREATE TABLE publication_operation_claims (operation_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES publication_intents(operation_id), method TEXT NOT NULL CHECK (method IN ('lifecycle','reference_claims','issue_occurrences')), digest TEXT NOT NULL) WITHOUT ROWID;
CREATE UNIQUE INDEX publication_claim_methods ON publication_operation_claims (publication_id, method);
```

Claim IDs deliberately do not reference child operations: before application, those operations must not exist. Claims remain permanently after release. The parent operations method is `identity_publication`. Canonical stored request text/hash must match the request codec. Store the actual lifecycle planner output as canonical ASCII JSON `{"revisions": [...], "lineage": [...]}` (existing eight-field planned rows and existing seven-field lineage rows); both arrays are empty without lifecycle work. The parent operation digest is existing `_digest(["identity_publication", spec_id, operation_id, request_json, plan_sha256])`, binding the request and retained plan. Hash request/plan/application ASCII bytes and completion payload UTF-8 bytes. No JSON numeric ID/counter fields are added.

The immutable preparation receipt is a detached dict with exact keys `version` (string `"1"`), `workspace_uuid`, `epoch_uuid`, `spec_id`, `operation_id`, `request_sha256`, `plan_sha256`. Read receipt namespace identity from the validated metadata on that same connection, not an instance-only field: existing upgrade/restore audits pass the IdentityStore class to connection-owned validators. Application receipt is `{"version":"1", "publication": preparation_receipt, "operations":[{"method": method, "operation_id": child_id, "receipt": existing_child_receipt_as_array}, ...]}` in request method order. Release receipt is `{"version":"1", "publication": preparation_receipt, "application_sha256": application_receipt_sha256, "completion_sha256": completion_payload_sha256}`. A read/pending result has exact keys `preparation`, `state`, `request` (canonical request JSON string), `application_receipt` (canonical JSON string or None), `completion_payload` (exact string or None). Return detached values, not live row dictionaries. All receipts must retain their original meaning after restart, release and later entity revisions.

**Preparation and atomic ownership:** A fresh preparation validates all lifecycle and projected binding requests in one BEGIN IMMEDIATE snapshot using the existing planner/projected binding helper; it does not apply any child operation or materialize reserved IDs. Retain the planner rows/lineage, parent operation, exact request and every child-ID claim atomically. Compute child digests using unchanged existing formulas: lifecycle `_digest(["lifecycle", spec_id, lifecycle_payload])`; binding `_digest([method, spec_id, child_id, binding_payloads])`. Reject child IDs already in operations or claimed by any publication in any spec, including a matching previously executed request; reject parent/child collisions and conflicting parent reuse. Invalid requests or conflicts roll back the entire preparation. A valid exact retry authenticates the retained original request/plan/claims and returns its original preparation receipt before replanning against later current heads; changed arguments fail. Do not reclaim abandoned allocations or synthesize a new publication ID.

**Pending write guard:** Integrate one private guard into existing `IdentityStore._operation`, covering all new reserve/import/lifecycle/reference/issue/publication writes. While state is prepared or applied, all new operations for that spec fail; other specs can proceed except they cannot take globally claimed child IDs. Exact already-completed ordinary retries remain read-only receipt retries, with existing conflicting-argument behavior intact. A claimed child ID cannot be executed publicly while its owner is prepared, even with identical arguments; after application/release its exact original receipt can be replayed. Permanent claims prevent method/spec/digest takeover at any state. Do not protect only lifecycle writes, use process-global/thread-local flags, or release the guard as soon as ledger application succeeds.

Use a private per-call store adapter for application that delegates existing store validators/receipts and overrides only `_operation` to pass a private owner ID into the common gate. The common gate may gain an optional keyword-only `_publication_id=None`; never expose that parameter through ordinary public writers. Validate owner, pending state, exact claimed method/spec/digest and request association before permitting a child insert. A missing child operation in applied/released state is damaged history, never permission to recreate it, even with matching arguments. No alternate INSERT path or copied operation-conflict logic. The spec pending lookup and global child claim lookup must be indexed, not scans of all publications/entities. A normal unclaimed operation without a pending spec must retain existing allocation/import algorithms and receipt behavior.

**Apply, then release:** Apply reauthenticates the prepared record, request, plan, claims and current baseline, then invokes the unchanged lifecycle writer and binding writer in method order on its one caller connection. Compare persisted revision/lineage rows to the retained exact plan and retain the exact child receipts in one atomic application receipt; only then change state to applied. A fault anywhere rolls back every child effect and retains the prepared intent/guard. Applied/released retries authenticate and return the original application receipt, not a recomputed latest result. An empty batch still gets an empty operations application receipt and does not release its guard.

Release accepts only an applied record and an exact nonblank/NUL-free UTF-8 completion payload, retains that exact payload/hash and transitions to released in the same transaction. It does not call a graph writer or claim the supplied evidence was independently verified; that authority belongs to the existing completion owner, which is not wired here. Exact released retries return the original release receipt; a changed completion payload fails. Prepared records cannot release, and no operation can rewind state or delete history/claims. No auto-release on process exit, elapsed time, backup, restore, failed validation, ledger application or ordinary audit. The absence of an automatic cancellation route is deliberate fail-closed behavior; do not add an arbitrary guard-clearing escape hatch.

**Authentication and migration:** Validate exact schema versions 1/2/3/4, with explicit upgrade required for older opens. Audit each source version before upgrade/restore destination claim: lifecycle for 2+, bindings for 3+, publication journal for 4. Current audit includes exact decimal-string counts for both new tables and validates parent operations, request/plan hashes and digests, complete exact child-claim sets, ownership, allowed method/state, and state/receipt associations. Prepared records have no child operations/rows/receipts and their retained plan/projected bindings still validate against the blocked baseline. Applied/released records have every exact child method/spec/digest and authenticated original receipt, and their persisted revisions/lineage exactly match retained planned rows (including content hashes, reasons, subjects, kinds/ordinals and operation IDs); do not replan released requests against newer current heads. Validate unexpected/orphan intent/claim/parent-operation associations through audit unions, not only rows reachable from well-formed parents. Changed or missing receipts/claims/plans, malformed JSON or premature/partial child application fail closed. Detectable corruption is not a repair finding; coherent malicious rewriting of all SQLite history/hashes is not cryptographic tamper protection.

Freeze v3 DDL in the new SQL fixture from the reviewed existing source, not from the schema under test. Upgrade adds only missing layers and leaves marker identity, all labels/history, counters, reservations and original receipts unchanged. Current no-op upgrade is idempotent. Backup/restore carry pending/applied/released intents and permanent claims; restoring a DB is not authority to promote files or clear its guard. Update former current-v3 tests so v3 remains a genuinely frozen old fixture and v4 is tested as current; never relabel a newly created v4 DB as v3 in a parameter name.

**First regression before production edits:**

```python
def test_prepared_intent_blocks_new_spec_writes_without_applying_reserved_ids(tmp_path):
    from harness.element_identity_store import IdentityStore, IdentityStoreError
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_request_codec import encode_request
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    payload = encode_request("lifecycle", (ElementCreate(label, "Scene", "Body", "reserve"),))
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
    request = PublicationIntentRequest("a" * 64, "controller recovery bytes", (
        PublicationOperation("lifecycle", "publication-child", payload),
    ))
    receipt = store.prepare_identity_publication(spec_id="demo", operation_id="publication", request=request)
    assert receipt["operation_id"] == "publication"
    assert store.lookup(spec_id="demo", element_id=label) is None
    with pytest.raises(IdentityStoreError, match="pending"):
        store.reserve(spec_id="demo", kind="FR", operation_id="later", count=1)
    assert store.high_water(spec_id="demo", kind="FR") == "1"
```

- [ ] Add the real reservation/codec regression with unit marker, run the new focused unit module with the checkout virtualenv, and retain actual missing-publication-module RED after the reservation succeeds before production edits.
- [ ] Implement strict request types/codec, additive DDL, journal helpers/common guard and public wrappers. Cover mixed lifecycle/reference/issue operations, empty operation batches, every lifecycle variant and transition kind, imported/adopted targets, old active versus projected terminal issue revisions, unassessed references, CRLF/Unicode and 5,000-digit revision strings. Verify exact old receipts, not just counters.
- [ ] Exercise every public writer under a prepared and applied guard; same/different specs, parent/child/global operation reuse, exact prior retries, reserved child execution attempts and arbitrary internal-owner mismatches. Assert full SQL-dump invariance for rejected calls and all-or-nothing child rollback. Query plans for both guard lookups must use indexes without a full scan/temp sort.
- [ ] Exercise request encode/decode round trips, duplicate JSON keys, numeric/bool/null/unknown fields, invalid method/order/duplicates, string batches, subclasses/frozen mutations and malformed inputs rejected before transaction entry. Direct helpers require an active caller transaction and neither change PRAGMAs nor open/finish another transaction. No test may count a fabricated publication/graph assessment as external authority.
- [ ] Use real SQLite fault injection between lifecycle and each binding write, before application-state update and before release-state commit; reopen and verify pending/applied states plus original receipts. Test full audit with missing/changed claims, plans, hashes, parent/child ownership, orphan rows, incomplete/premature child application and receipt damage. Test frozen 1/2/3 upgrades, malformed old histories rejected before mutation, transactional DDL rollback, no-op upgrade, and backup/restore of every intent state with the guard retained.
- [ ] Add bounded spawn-process tests for competing preparations of one spec (one winner), exact same-request preparation retries, cross-spec progress/global child collision, and process termination after committed prepare/application followed by restart/retry. Use IPC synchronization, bounded joins and cleanup, not sleep-based race assertions. Record actual outcomes.
- [ ] Run final covering modules once: the two new publication modules, `tests/unit/test_element_identity_store.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_element_identity_admin.py`, `tests/unit/test_element_identity_preview.py`, `tests/unit/test_element_identity_binding_preview.py`, `tests/unit/test_element_identity_transaction_composition.py`, `tests/unit/test_element_identity_request_codec.py`, and `tests/integration/test_element_identity_store.py`. Include the existing million-import case once because allocation's common guard changes; retain its measured output (`-rP` is sufficient). This is a scoped suite, not full repository/live/provider verification; no unchanged post-commit repeat.
- [ ] Document all APIs/formats/state transitions, spec-wide guard tradeoff and the difference between storage receipts and authenticated publication/semantic/graph completion. Self-review all writers/upgrade/restore/audit dispatch, run `git diff --check`, commit task files only, and retain actual command/RED/GREEN output and measurements in the report. Label counterfactual coverage reasoning separately from empirical mutation tests. Root owns plan/ledger/checkpoints and independent review.

## Remaining integration

This phase deliberately does not activate any producer. A subsequent existing-completion-owner integration must construct and authenticate a complete versioned recovery payload, select every typed/opaque source dependency, verify structural/edit-scope/semantic approval, and prepare this journal while its canonical source and ledger snapshots are coherent. Only that owner may coordinate file acceptance, ledger application, mandatory graph/history projection and release after normal-exit source verification. Run-local/manual paths and final export must share it without duplicate revisions. Historical reconciliation, managed feature snapshots, provider scope, all seven producers, bounded repair and final offline/live checkpoints remain required.
