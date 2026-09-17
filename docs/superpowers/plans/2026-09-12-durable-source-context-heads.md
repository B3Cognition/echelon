# Durable source-context heads implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Retain an explicit accepted selected-source baseline and advance it atomically with the existing identity publication journal, preserving original receipts and history across retry and recovery.

**Architecture:** Add explicit source-context registration and indexed current-head reads to the existing identity store. An optional, closed version2 publication request binds its context, predecessor receipt and complete original source baseline. The existing publication prepare/apply/release owner validates and applies the source effect in the same SQLite transaction as its existing lifecycle/reference/occurrence effects. Source contexts are low-level caller-declared observation scopes, not managed-run registration or semantic certification.

**Tech Stack:** Existing SQLite authority, additive schema5 with frozen schema4 compatibility, canonical source manifest/baseline codecs, expected final source projection, existing publication journal and caller-owned transactions, real subprocess/rollback/recovery tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- A pending publication blocks conflicting writes until reconciled.
- The local database is authoritative for allocation; graph and Markdown are consumers, not independent allocators.
- No live controller/provider activation, managed-run feature registration, source-root relocation, historical reconciliation, graph/memory effects or second publication/lifecycle writer. Explicit source-context acceptance does not prove caller ownership, complete dependency selection or semantic approval.

---

### Task 1: persist source contexts and source-bound identity publications

**Files:** Create `src/harness/element_identity_source_store.py` and `tests/unit/test_element_identity_source_store.py`. Modify `src/harness/element_identity_schema.py`, `src/harness/element_identity_store.py`, `src/harness/element_identity_publication.py`, `src/harness/element_identity_publication_store.py`, and `src/harness/element_identity_snapshot.py` for the exact composition/audit described below. Update schema-version/count assertions in the affected existing identity tests only where required by the additive schema, preserving old-version golden fixtures. Document in `docs/element-identity-storage.md`. No CLI verb, parser, candidate, source capture/codec/projector/guard, publisher, controller/state, provider, prose, graph or memory implementation changes. Root owns plan/ledger.

**Existing dependencies:** `validate_source_manifest` and `decode_source_manifest` validate metadata-only source claims; `encode_initial_publication_sources` / `decode_initial_publication_sources` preserve complete original source bytes and sealed associations; `snapshot_source_manifest` computes exact selected observation metadata; `project_publication_source_manifest` computes expected full final metadata. Read the existing signatures and use them directly. Do not fabricate captured objects, duplicate these encodings/projections, or read current files to reconstruct a retained preimage.

**Public store interfaces:**

```python
def register_source_context(
    self, *, spec_id: str, context_id: str, operation_id: str,
    manifest: SourceManifestSnapshot,
) -> dict: ...

def source_context(self, *, spec_id: str, context_id: str) -> dict | None: ...
```

Use existing identifier validation for spec/context/operation strings. `context_id` is an opaque controller-selected scope name within the canonical spec; it is not inferred from a pathname, run, document maximum or current namespace. Registration is an explicit caller acceptance of one validated complete selection, not automatic initialization or assessment of existing identities. It has no filesystem effect. A new context can coexist with other contexts in the same spec, but registration cannot replace an existing context or reset its history. Future managed-run wiring must authenticate which exact context and namespace belong to each run and ensure a complete selection.

Registration validates an exact detached manifest through the new codec, then records one ordinary globally owned operation with method `source_context` and digest `authority._digest(["source_context", spec_id, context_id, manifest.payload])`. It shares the existing common operation/pending guard. Exact same-operation retries return the original registration receipt even after later source publications or while another publication is pending; changed arguments, reused global operation IDs/child claims or a different operation attempting the same context fail. No current-head overwrite, implicit context re-registration, or counter changes.

Both methods return detached string-tree records with exactly: `version` string1; the existing namespace fields `workspace_uuid` and `epoch_uuid`; `spec_id`; `context_id`; `registration_operation_id`; `operation_id`; `sequence`; and `manifest` containing exactly `payload` and `sha256`. Registration's operation_id is its registration operation and sequence is canonical string0. A current applied publication head uses its parent publication operation ID and positive canonical decimal sequence, with the projected final manifest. A missing context returns None only if neither retained context nor associated source-publication/registration operation indicates damaged missing authority. Reads use one query-only caller transaction, validate stored associations, and never repair or advance state. Source records do not enter the materialized identity-history wire; that snapshot still audits the full authority.

**Closed optional publication source claim:** Extend the existing exact frozen `PublicationIntentRequest` by adding trailing field `sources: PublicationSourceClaim | None = None`, preserving all existing positional/default construction. Define and export the new exact frozen/slots type in `element_identity_publication.py`:

```python
@dataclass(frozen=True, slots=True)
class PublicationSourceClaim:
    context_id: str
    expected_operation_id: str
    baseline_payload: str
```

Validate exact immutable types/intact fields and canonical strings at construction and every encoding/entry, not merely at the first constructor. `baseline_payload` must equal the unchanged initial-source codec's canonical encoding after decoding; it therefore retains original prefix-zero images and full selected bytes. Its marker manifest_sha256 must equal the enclosing publication request's manifest_sha256. Expected source-before metadata is computed from its retained trees/files; expected source-after metadata comes from the existing final projector. The claim supplies no arbitrary after hash or alternate selection.

When `sources is None`, request version1 bytes, closed key set, decoded object, operation ordering and receipts remain exactly unchanged. When sources is present, encode version string2 with exact root keys version/manifest_sha256/recovery_payload/operations/sources; sources has exact keys context_id/expected_operation_id/baseline_payload. No sources:null variant, optional unknown fields, numeric versions, duplicate keys or alternate shapes. Existing child request codecs and three child methods remain unchanged. Decode version1 with sources=None and version2 with the exact claim; reject version2 without sources and version1 with sources. Newly introduced claim-validation boundaries normalize ordinary malformed/Unicode/recursion/structural errors to bounded errors without untrusted traceback context; preserve BaseException. No I/O in codecs. Do not reinterpret opaque recovery_payload contents as a source format or silently change the existing completion_payload contract.

**Additive schema5:** Preserve exact current schema4 DDL as `SCHEMA_V4`; current marker format and PRAGMA user_version remain1. Add only these two tables and required indexes to the existing schema; no rewrite of old rows or receipts:

- `source_contexts`: spec_id TEXT, context_id TEXT, registration_operation_id TEXT, manifest TEXT, manifest_sha256 TEXT, all NOT NULL; head_publication_id TEXT nullable REFERENCES publication_intents(operation_id); PRIMARY KEY(spec_id,context_id), UNIQUE registration_operation_id, FOREIGN KEY registration_operation_id REFERENCES operations(operation_id); WITHOUT ROWID. Initial manifest/registration binding is immutable. Only head_publication_id advances, in the same application transaction; null denotes the original registration head.
- `source_publications`: publication_id TEXT PRIMARY KEY REFERENCES publication_intents(operation_id); spec_id TEXT, context_id TEXT, sequence TEXT, predecessor_operation_id TEXT REFERENCES operations(operation_id), manifest TEXT, manifest_sha256 TEXT, all NOT NULL; application_sha256 TEXT nullable; FOREIGN KEY(spec_id,context_id) REFERENCES source_contexts(spec_id,context_id); canonical positive decimal sequence CHECK using the existing decimal SQL pattern; WITHOUT ROWID. This retains one source plan per parent publication, not a fourth child writer or free-standing source-advance operation.
- `source_publication_sequences`: UNIQUE INDEX on source_publications(spec_id,context_id,sequence).
- `source_publication_heads`: INDEX on source_publications(spec_id,context_id,length(sequence),sequence) WHERE application_sha256 IS NOT NULL.
- `source_registration_specs`: INDEX on operations(spec_id,operation_id) WHERE method='source_context', supporting spec-bounded orphan-registration checks when a requested context is missing.

Use the table primary key/unique registration constraint for exact lookups. Current-head reads require the context's independent head_publication_id to match the highest accepted source publication found through the partial numeric-order head index. A missing pointed row, pointer-only rewind, pointer to a prepared/other-context parent, or a highest-row deletion must block, never silently fall back to an older surviving source row or registration. Do not repair either pointer or history. This is consistency detection, not a cryptographic defense against a coherently substituted older entire database. No lookup scans all historical Markdown, entities, source revisions or publications. When a context row is absent, associated source-publication rows or any orphan source-registration operation in that spec indicate damaged authority; a registration operation retains only a digest, so do not pretend its deleted context name can be reconstructed. Use the new partial registration index for this conservative spec-bounded check. Sequence arithmetic uses existing unbounded decimal helpers, never a SQLite integer or int-string conversion with a global digit-limit change. There is no sequence or context count application cap. The initial source context is sequence0; each accepted source publication increments its predecessor's sequence, including equal-content/no-op publications. Original receipt identity, not hash equality alone, is the compare-and-swap token.

**Journal composition and current-head CAS:**

1. Source-less version1 publications retain all existing behavior, including same-spec write guards and immutable original receipts. This low-level addition does not activate managed-run enforcement or require every legacy publication to carry a source claim.
2. On first prepare of a source-bound request, require the registered context; its current operation_id must equal sources.expected_operation_id, and its exact current manifest must equal the source-before fingerprint from the retained baseline. Selection paths must remain exactly those of registration (same ordered tree roots and explicit files); this equality also holds for the projected after manifest. Changing/omitting registered dependencies or pairing one context with another context's predecessor cannot silently accept a new selection. A self-consistent request deliberately naming another registered context is judged against that context; this library cannot authenticate which context the live caller should have selected. Store the derived next sequence, exact predecessor, projected after manifest and nullable application digest with the existing parent intent and child claims in one transaction. Parent request bytes/digest include the closed source claim; every stored source-plan value must be reproducibly bound to it and the original predecessor, not an independent opaque authority.
3. Original prepare retries validate original retained records and return the original preparation before comparing against today's source head. They must still work after later accepted publications. A new operation with an old predecessor fails even when before/after hashes happen to equal current bytes. Pending publication still blocks all conflicting new spec writes through release.
4. Existing journal apply remains the only lifecycle/reference/occurrence application owner. In the same transaction, it materializes existing child effects, records source acceptance and compare-and-swaps source_contexts.head_publication_id from its exact predecessor pointer (null for registration) to this publication. Its source-bound application receipt is closed version string2 with exactly publication, operations and sources in addition to version. `sources` is the same full source-context receipt described above for the new head. Compute the receipt without a circular self-hash; store its canonical SHA in source_publications.application_sha256 and in the existing publication application receipt fields. Source-less application receipts remain byte-for-byte version1. SQL or commit failure cannot expose only identity history or only the source head; uncertainty after an actual completed commit is recovered by exact original receipts, not by claiming rollback happened.
5. Prepared source rows have null application_sha256 and do not become current heads. Applied/released rows must match the parent application's exact receipt/digest and derived source receipt. Retry returns the original application after later heads, never reapplies or resets them. Release preserves its existing version1 receipt shape and pending guard semantics; its application hash binds the exact version1 or version2 application bytes. It does not certify filesystem freshness, semantic review or a graph result merely because the source head was accepted.
6. Missing/orphan/mismatched source rows, wrong spec/context/predecessor/sequence/selection, malformed manifests, premature acceptance or inconsistent parent application state fail closed on the relevant read/retry/audit. Even recomputed local hashes cannot make a source row disagree with its source-bound parent request and retained predecessor. Validate recorded predecessor links without recursive all-history replays on each head lookup. Full audit checks complete registration/source chains, contiguous sequence increments, no forks/orphans, original registration method/digest, all source-bound parent associations and highest accepted head. Do not require a historical accepted parent to remain today's latest head.

Implement focused connection-owned helpers in `element_identity_source_store.py` for registration/head/preparation/application/validation/audit, called by the existing owners. Every exported-to-owner helper requires an already active caller transaction, revalidates its inputs, and never begins/commits/rolls back, changes PRAGMAs, reads files, acquires publication locks or calls providers. Preserve the existing short DB-transaction ownership and lock order; actual guarded filesystem promotion remains the caller's responsibility. Do not use `_ApplicationStore` to invent a fourth child claim or bypass its permanent ownership checks.

**Schema compatibility and audit routing:** Recognize frozen versions1–4 for explicit upgrade/restore, preserving all original DDL/metadata/rows and old version1 publication request bytes. Upgrade creates only missing additive structures; never silently open/mutate an old schema. Update all current-schema full-audit paths and method allowlists/counts, including `element_identity_snapshot.snapshot`'s `_audit` call, store audit/upgrade/restore and publication audit. Old schema4 publication auditing must not query nonexistent source tables and must reject a source-bearing version2 request in a schema that never supported it. An explicit internal source-state/audit-version parameter is permitted; do not infer support by suppressing missing-table errors. Binding audit remains enabled on versions3/4/5 and publication audit on4/5, not just the prior exact version values. Marker format stays1; existing history snapshot payload/digest does not gain source/publication rows.

**Required first regression before production:**

```python
def test_real_source_context_registration_retains_original_manifest(tmp_path, secure_posix):
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs/notes.md").write_bytes(b"FR-1000000\r\n\x00\xff")
    prepared = SquadPublicationTransaction.begin(project, squad, "5" * 32).seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("absent",)) as initial:
        assert initial.trees[0].files[0].content == b"FR-1000000\r\n\x00\xff"
    manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    store = IdentityStore.initialize(project)
    receipt = store.register_source_context(
        spec_id="demo", context_id="run-source", operation_id="source-registration",
        manifest=manifest,
    )
    assert receipt["sequence"] == "0"
    assert receipt["manifest"] == {"payload": manifest.payload, "sha256": manifest.sha256}
    assert IdentityStore.open(project).source_context(spec_id="demo", context_id="run-source") == receipt
```

Real capture/factory/store initialization must succeed before the missing method causes RED; notify root before production changes. Scope secure-POSIX skips to real capture/promotion tests; pure codec and ordinary SQLite cases must still run on supported non-POSIX environments.

- [ ] Obtain first actual missing-method RED, implement registration and exact source-context read with additive schema, then focused GREEN. Build the source-bound request and existing journal composition in the same task; do not declare the task done at registration only.
- [ ] Independent exact registration/source-bound request/application receipt expectations; preserve unchanged version1 golden bytes and receipt shapes. Real before/final captures include hidden/binary/CRLF/wide IDs, absent files, empty directories, modes, nested parents, writes/deletes/no-ops. No staged/current file reads inside the store or codecs.
- [ ] Prove new registration versus exact retry/conflict, global operation/child ownership, missing context and same/different-spec behavior; changes to registered selections, including emptying a nonempty selection, reject. An explicitly registered genuinely empty selection remains a valid metadata context, not proof of dependency completeness. Same bytes with a stale predecessor still reject. Equal-content accepted publication advances the sequence once; old registration/prepare/apply/release retries retain their original receipts after two later heads and reopen.
- [ ] Real combined lifecycle/reference/occurrence/source application is atomic and retains all seven-family labels/old revision evidence. Add source-only publication and an old source-less publication control. Preserve pending all-writer exclusion through release; registration joins that existing guard. Source context creation alone allocates no element IDs, changes no revisions and adds no identity-history wire rows.
- [ ] Inject SQL failures at source-plan insertion, child effect, source acceptance/application receipt writes and before COMMIT; assert rollback leaves exact prior head, history and guard. Inject a failure reported after actual COMMIT in an isolated connection wrapper, reopen and prove exact retry returns the single coherent committed receipt; label this uncertain outcome, not rollback. Real separate-process competing source-bound prepares/CAS must produce one winner without duplicate sequences or source-head regression.
- [ ] Compose existing publish_sources callbacks with store prepare/apply in a test only: real interrupted filesystem prefix leaves a prepared identity/source intent and original source head; reload retained baseline from stored version2 request, retry to exact final bytes/head, then release explicitly. A rejected source drift never reaches prepare; after-callback failure does not falsely release/discard pending recovery material. This is a narrow caller-composition test, not live SquadController integration or semantic approval.
- [ ] Parameterize closed request/claim validation, deleted/damaged exact frozen fields, noncanonical source baseline, marker mismatch, malformed Unicode/deep input and bounded errors/BaseException. Damage registration/plan/application/predecessor/sequence/source hashes with real SQLite, including recomputed local hashes; relevant reads/retries/audit and backup/restore must reject without repair. Include deleting the highest accepted source row with its parent/pointer retained, clearing/rewinding the pointer with later history retained, and cross-context/prepared pointer substitution; no current-head fallback is permitted. No passing test is claimed as an observed RED.
- [ ] Freeze exact independent schema4 DDL including all publication indexes, upgrade real prepared/applied/released legacy journals and preserve their original receipts/guard/marker bytes. Reject source-bearing records in old schema auditing. Exercise schema5 audit, snapshot full audit, backup/restore and integrity contradictions; update only genuinely changed current-schema expectations in existing tests.
- [ ] Inspect EXPLAIN QUERY PLAN for the source head and exact context/parent lookups; repeated current-head reads must use the required index rather than replay all source history. Exercise unbounded sequence parsing/comparison without pretending to have physically committed thousands of source publications when a synthetic numeric boundary is used.
- [ ] Final covering run once: new tests/unit/test_element_identity_source_store.py; existing tests/unit/test_element_identity_publication.py, test_element_identity_store.py, test_element_identity_lifecycle.py, test_element_identity_bindings.py, test_element_identity_transaction_composition.py, test_element_identity_binding_preview.py, test_element_identity_snapshot.py, test_element_identity_admin.py, test_element_identity_request_codec.py; tests/integration/test_element_identity_store.py. Include the existing million-record capacity case once for this schema/guard integration and report actual storage/open/next-allocation timings, not a million source-head or assessed-revision claim. Do not run broad full-unit/live/provider/install or postcommit repeats. Self-review atomic ownership, version compatibility and receipt/CAS behavior, run actual diffcheck, document limits, commit task files/full report. Root provides independent review.

## Remaining integration

Source-context names and complete selections are explicit trusted caller inputs. This phase does not choose a managed-run feature snapshot, physical run-to-canonical source relocation protocol, authenticated context/dependency refresh, new-run historical reconciliation, provider proposal/reservation protocol, graph staging API or retarget policy. Legitimate external-dependency changes shared by different contexts still require an authenticated owner transition; they must not silently overwrite accepted heads to make a stale baseline pass. Those owners must select/authenticate the context and namespace, protect ledger access, validate all candidate sources and semantic judgments, account for exact graph bytes, retain pending recovery materials and gate completion. No producer is activated by this library change. Bounded discovery repair, revision-aware memory and live/offline controller matrices remain required.
