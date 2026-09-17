# Managed identity registration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Persist explicit, immutable genesis registration for a newly initialized identity-managed spec, binding its namespace, first run, physical spec root and accepted source context without activating a live producer.

**Architecture:** A small strict request codec and additive registry table share the existing identity authority, global operation ownership, pending guard and explicit upgrade/audit paths. Registration requires a fresh, unallocated canonical spec and a registered initial source context whose selected spec tree is present and empty. Querying retained registration stays independent of mutable run-state fields. This is a genesis record, not an active-run pointer, subsequent-run transition or complete managed workflow.

**Tech Stack:** Existing SQLite authority and source-context APIs, canonical string-tree JSON, exact frozen requests, indexed lookup, real transaction/process/upgrade tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- A pending publication blocks conflicting writes until reconciled.
- The local database is authoritative for allocation; graph and Markdown are consumers, not independent allocators.
- No live controller/provider activation, state-field mutation, retarget/source relocation, historical reconciliation, semantic certification, graph/memory effects or new publication/lifecycle writer. Persisted registration alone is not end-to-end enforcement or dependency-completeness proof.

---

### Task 1: store immutable genesis registration for new managed specs

**Files:** Create `src/harness/element_identity_managed.py`, `src/harness/element_identity_managed_store.py`, `tests/unit/test_element_identity_managed.py`. Modify `src/harness/element_identity_schema.py`, `src/harness/element_identity_store.py`, `src/harness/element_identity_snapshot.py` only for request-facing methods and additive schema/audit routing; update genuinely affected current-schema expectations in existing tests and `docs/element-identity-storage.md`. Do not modify source-context, publication request/journal, lifecycle, parser, provider, state, controller, CLI, graph or memory implementations. Root owns plan/ledger.

**Public request and codec:** Define exact frozen/slotted `ManagedIdentityRequest` in the new pure module with exactly these string fields in this order: `workspace_uuid`, `epoch_uuid`, `run_id`, `context_id`, `spec_path`, `source_registration_operation_id`, `source_manifest_sha256`. Define `encode_managed_identity_request(request: ManagedIdentityRequest) -> str` and `decode_managed_identity_request(payload: str) -> ManagedIdentityRequest`. The canonical ASCII JSON object has exactly those fields plus version string`1`. Use existing strict JSON and canonical JSON policy, not a second serializer. Reject duplicate/unknown/missing keys, numeric versions/fields, malformed UTF-8 strings, noncanonical JSON, subclasses, deleted/mutated frozen fields, blank identifiers and invalid canonical project-relative `spec_path`. Use the existing source-path validator for spec_path, existing lifecycle text validator for identifiers, exact canonical UUID strings for namespace fields, and exactly64lowercase hexadecimal characters for source_manifest_sha256. Revalidate at construction and every codec/store/helper entry. Normalize ordinary malformed-input exceptions to bounded errors without untrusted chained context; preserve BaseException. No I/O, database, lock or current-file lookup in codecs.

**Public store interfaces:**

```python
def register_managed_identity(
    self, *, spec_id: str, operation_id: str,
    request: ManagedIdentityRequest,
) -> dict: ...

def managed_identity(self, *, spec_id: str) -> dict | None: ...
```

The returned detached record has exactly: version string`1`, workspace_uuid, epoch_uuid, spec_id, operation_id, run_id, context_id, spec_path, source_registration_operation_id, source_manifest_sha256. Namespace values come from the actual retained authority and must equal the request, never be silently replaced. The version identifies the fixed seven-family durable-identity genesis contract; it is not a configurable subset, boolean opt-out or a claim that enforcement is already active.

Record one globally owned ordinary operation with method `managed_identity` and digest `authority._digest(["managed_identity", spec_id, operation_id, request_payload])`. No reservation, source acceptance, lifecycle revision or publication is created as a side effect. Existing common pending/child-ownership guards apply. First registration is atomic with its operation record. Exact same-operation/same-request retries return the original record after later reservations, revisions, source publications, pending publications and reopen. Retry validation precedes first-enrollment emptiness conditions. Changed requests, wrong namespace, reused operation IDs/child claims, another operation for the same spec, or the same run_id for another spec reject. No implicit authority initialization and no update/delete/replace API.

**First-enrollment prerequisites:** After resolving exact existing retries through bounded retained-record checks, validate the full existing authority for first enrollment in its registration transaction, before inserting its new ordinary operation, then require no counters, reservations, entities, lifecycle history, reference/occurrence bindings, or identity publications for this spec. Do not audit a deliberately half-inserted registration or split this transaction to avoid an orphan check. Other specs may have arbitrary valid history; existing source-context registrations for this spec are permitted. This explicit initialization path does not enroll a legacy/imported or already allocated spec, even if its rendered files or active rows are now empty. Do not reset history to make enrollment pass.

Require the exact existing source context for spec_id/context_id; it must currently be its original sequence`0` registration, its registration operation must equal source_registration_operation_id, and its original manifest SHA must equal source_manifest_sha256. Decode its original manifest with the existing source-manifest codec. spec_path must equal one selected tree root, not merely be a prefix or an unselected descendant. That tree must exist, contain exactly its root directory entry and no files. Its valid existing directory mode is preserved; do not invent a new mode restriction. Other selected trees/files may contain real external dependency bytes/metadata. The empty spec-tree requirement is an explicit fresh-enrollment check, not proof that the caller selected every dependency. A genuinely empty overall selection cannot supply the required spec tree. Do not read present files or infer run/spec paths from naming conventions.

Persisted registration is immutable genesis information. Reads and exact retries validate the original source registration association and its retained original manifest including the independently retained source_manifest_sha256, not require its source head to remain sequence0 or its spec tree to remain empty today. Rewriting a source registration manifest and recomputing its local operation digest must still contradict the retained genesis hash. Later accepted sources and identity revisions must not invalidate the genesis record. Read validation must distinguish the source context's immutable registration from its current head; reuse existing helpers on the same active transaction, without widening source helper APIs or reconstructing current filesystem bytes.

**Schema6:** Freeze exact current schema5 as `SCHEMA_V5`. Marker format and PRAGMA user_version remain1. Add only:

- `managed_identity_specs`: `spec_id TEXT PRIMARY KEY`, `run_id TEXT NOT NULL UNIQUE`, `context_id TEXT NOT NULL`, `operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id)`, `request TEXT NOT NULL`, `request_sha256 TEXT NOT NULL`, and FOREIGN KEY(spec_id,context_id) REFERENCES source_contexts(spec_id,context_id); WITHOUT ROWID. All columns including spec_id are non-null. Stored spec/run/context columns must reproduce the request and returned record exactly; the request retains namespace/spec-path/source-registration binding. There is one immutable genesis record per spec, not an implicit current-run replacement.
- `managed_identity_operations`: partial INDEX on operations(spec_id,operation_id) WHERE method='managed_identity'. This supports spec-bounded missing-registration detection and audit without whole-operation scans on ordinary reads.

Current reads use the table primary key and indexed parent operation/source-context lookups. Missing registry rows return None only when no retained managed_identity operation for this spec indicates damage. A row missing its operation, wrong method/spec/digest, wrong redundant run/context columns, invalid request/hash, mismatched namespace, missing/wrong original source registration or malformed original selected tree blocks without repair. Tests must include recomputed local hashes, not only invalid SHA strings. Source-context current corruption must not be silently used to manufacture a fresh genesis; its ordinary current-state integrity checks may reject, but current identity-history child tables must not be scanned merely to read registration. Full audit checks every registry row and orphan registration operation. This is local consistency detection, not protection against coherently substituting an older entire database.

**Schema/audit compatibility:** Explicit upgrade/restore recognize frozen schemas1–5. Ordinary open/transactions still require current schema. Source audit remains enabled on5/6, publication on4/5/6, bindings on3/4/5/6, lifecycle on2–6. Add an explicit internal `managed_state=False` audit parameter and route current full audits through it, including snapshot capture, administrative audit, backup before destination claim, upgrade and restore. Old schema5 audit must not query the nonexistent new table and must reject unsupported managed_identity operation methods. No missing-table suppression or reinterpretation of old rows. The materialized identity-history wire/digest remains unchanged by genesis registration. Source/publication version1/version2 wires and original receipts remain unchanged.

Implement connection-owned helpers in the new store module: active transaction required, validated exact inputs, no begin/commit/rollback/PRAGMA ownership, no file reads or provider/lock calls. Existing IdentityStore owns transactions. Do not alter the global guard to enforce live managed policies in this task; future controller/producer integration must consult the persistent record, bind current run transitions explicitly, and refuse metadata removal/downgrade. A different run for an already enrolled spec requires a separately specified retained transition, not resetting this genesis row.

**First actual regression before production:** Add this real-capture enrollment test, using the project's secure-POSIX fixture only for this filesystem case. Do not fake the source manifest to reach the missing-method failure.

```python
def test_register_fresh_managed_spec_retains_namespace_and_source(tmp_path, secure_posix):
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    root = tmp_path.resolve()
    (root / "specs/demo").mkdir(parents=True)
    squad = root / "runs/first"
    squad.mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(root, squad, "6" * 32).seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    store = IdentityStore.initialize(root)
    source = store.register_source_context(spec_id="demo", context_id="first-source",
        operation_id="source-registration", manifest=manifest)
    assert source["sequence"] == "0"
    # Missing API is the first behavior under test; no production module import
    # should prevent the genuine capture/registration setup from executing.
    register = store.register_managed_identity
    from harness.element_identity_managed import ManagedIdentityRequest
    request = ManagedIdentityRequest(source["workspace_uuid"], source["epoch_uuid"],
        "first", "first-source", "specs/demo", "source-registration", manifest.sha256)
    receipt = register(spec_id="demo", operation_id="managed-registration", request=request)
    assert receipt == {"version": "1", "workspace_uuid": source["workspace_uuid"],
        "epoch_uuid": source["epoch_uuid"], "spec_id": "demo",
        "operation_id": "managed-registration", "run_id": "first",
        "context_id": "first-source", "spec_path": "specs/demo",
        "source_registration_operation_id": "source-registration",
        "source_manifest_sha256": manifest.sha256}
    assert IdentityStore.open(root).managed_identity(spec_id="demo") == receipt
```

- [ ] Run the first actual missing-method RED after real capture and source registration succeed; notify root before production. Implement smallest request/registration/read/schema path, then focused GREEN. Keep request and storage files focused.
- [ ] Independent closed request/receipt expectations, exact detached mutation behavior, malformed frozen fields/UUID/path/Unicode/depth/duplicate/type cases and bounded ordinary errors/BaseException. Pure codec/ordinary SQLite tests must not be skipped by a broad POSIX fixture.
- [ ] Real explicit enrollment rejects reservations (including abandoned gaps), imports, active/terminal entities, existing publications and non-initial source heads. Nonempty/missing/nested-only spec trees and wrong source registration/namespace reject; valid external dependencies and existing root modes remain supported. Rejection preserves exact SQL dump and source/history receipts.
- [ ] Same-operation exact retry after source advancement, seven-family materialization, pending journal and reopen returns immutable genesis; no duplicate operations, no new IDs or history-wire rows. Conflicts, permanent child claims, wrong spec/run/context/namespace and cross-spec run reuse reject. Unregistered spec query returns None; unknown registered-context selection is not inferred from paths.
- [ ] Real SQL failure during operation/registry insert and before COMMIT rolls back both records. A separately labeled after-actual-COMMIT uncertainty test reopens to the one original receipt. Two real spawned processes compete for one spec/run binding; one wins and no replacement is possible.
- [ ] Raw SQL corruption tests cover missing/orphan records and operations, altered request/columns/namespace/original source associations, including recomputed request/operation hashes. Query/full audit/snapshot/backup/restore must reject applicable contradictions without creating a successful backup or repairing rows. Prove indexed registry/operation/source lookups with EXPLAIN and prohibit identity child-history access during ordinary current registry reads.
- [ ] Construct independent frozen schema5 fixture with real registered/advanced source context and prepared/applied/released version2 journals. Explicit upgrade and restore preserve original source/publication bytes/receipts/marker. Ordinary old-schema open/write rejects. Old5 audit never touches managed tables, and unsupported managed operation rows fail. Existing frozen1–4 fixtures and audit routing remain valid.
- [ ] Final covering run once: tests/unit/test_element_identity_managed.py, test_element_identity_source_store.py, test_element_identity_publication.py, test_element_identity_store.py, test_element_identity_lifecycle.py, test_element_identity_bindings.py, test_element_identity_snapshot.py, test_element_identity_admin.py, test_element_identity_request_codec.py and tests/integration/test_element_identity_store.py. Deselect only the existing million-record capacity test by its actual inspected name: this task does not modify allocation/import/common-guard logic, and the immediately previous schema5 task measured it once; do not claim a schema6 capacity measurement. No full-unit/live/provider/install or postcommit repeat. If a final production self-review fix follows this run, report the earlier code point and run only affected modules for the amendment.
- [ ] Self-review exact original retry behavior, namespace/genesis versus current-head semantics, source association integrity, frozen audit routing and no live activation. Run diffcheck, document limits, commit all task/report files, return DONE only when final commits/report are complete. Root performs independent full original-base review.

## Remaining integration

The initial managed-run record does not bind later retarget/manual/replay run transitions, authenticate complete source selection or semantic proposals, or protect mutable runtime state by itself. Those existing owners must consume it before provider dispatch and completion, prevent removal/downgrade, isolate candidates, use reserved IDs, retain source/identity/graph recovery, and enforce all banzai branches. No initial registry entry is automatically created by normal initialization or legacy open. Historical enrollment requires explicit authenticated reconciliation rather than this fresh-only path. No provider allocation/proposal format, graph staging API or subsequent-run transition is chosen by this task.
