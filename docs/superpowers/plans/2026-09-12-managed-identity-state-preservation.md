# Managed identity state preservation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Preserve explicit managed genesis metadata through the existing state writer and initialization paths, rejecting replacement/removal without activating managed provider execution.

**Architecture:** A focused pure validator describes the exact existing genesis record. The existing transaction namespace reserves one new state key, and SquadStateStore validates and preserves it under its existing lock and durable writer. Explicit initialization may introduce a controller-supplied record; ordinary updates cannot. This protects state protocol integrity, not the origin of a supplied record or a missing durable database.

**Tech Stack:** Existing managed request codec, SquadStateStore, transaction namespace and prepared-result ownership/attestation, real filesystem state tests and simulated controller tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- No live enrollment or provider activation, new database schema, ledger writes, source/publication/lifecycle changes, semantic certification, retarget/source relocation or graph/memory effects.
- Existing state locks, revision CAS, preparation/routing attestations and durable writer remain the owners. No database access or publication lock acquisition while holding a state lock.

---

### Task 1: preserve immutable managed metadata in the existing state owner

**Files:** Create `src/harness/element_identity_state.py` and `tests/unit/test_element_identity_state.py`. Modify `src/harness/state_transaction_namespace.py` and `src/harness/squad_state.py` for the exact field/initialization/save/load behavior below. Add focused ownership tests to `tests/kernel/test_prepared_phase_result.py` or reuse their existing test helpers from the new test module; add one real-controller/simulated-provider prepared-initialization test to `tests/integration/test_squad_controller.py`. Document in `docs/element-identity-storage.md`. Existing `tests/kernel/test_squad_state.py` and `tests/unit/test_state_transaction_namespace.py` may gain covering cases. Do not modify managed registration/store/schema, controller/executor/provider/CLI/startup production files, source/publication/lifecycle/graph/memory implementations or role prose. Root owns plan/ledger.

**Exact pure record validation:** Define `MANAGED_IDENTITY_KEY = "managed_identity"` and `validate_managed_identity_record(value: object) -> dict[str, str]` in the new pure module. Accept only an exact dict with exactly these keys: version string`1`, workspace_uuid, epoch_uuid, spec_id, operation_id, run_id, context_id, spec_path, source_registration_operation_id, source_manifest_sha256. All values are exact strings. Reuse the existing `ManagedIdentityRequest` and its encode/decode validation for the seven request fields; use existing lifecycle text validation for spec_id and operation_id. Do not duplicate UUID/path/hash grammar or reinterpret source/counter widths. Return a detached exact flat dict, retaining every value unchanged. Reject unknown/missing keys, subclasses, numeric/boolean versions, None, malformed strings, altered structures and ordinary hostile-container failures with a bounded ValueError-family error and no untrusted exception context; preserve BaseException. No I/O or authority lookup. A valid record is a structurally valid caller claim; only a future trusted runtime owner can compare it to the actual registry.

The single state field `managed_identity`, when absent, retains legacy behavior. If present it must contain the exact validated genesis record; None, false, empty objects and partial records are invalid, not opt-out forms. The record's spec_id must match the state's exact string spec_id, and the state's exact run_id must match this initial record's run_id. This version is first-run-only; later run transitions require an explicit new bound state protocol, not relabeling the genesis record. Do NOT require mutable state spec_dir to equal genesis spec_path forever: the genesis root is original metadata, not a current-run/source pointer. Current physical scope and any allowed export/relocation must be authenticated by later runtime integration.

**Transaction ownership:** Reserve MANAGED_IDENTITY_KEY through a separate `MANAGED_IDENTITY_KEYS` frozen set included in `STORE_OWNED_TRANSACTION_KEYS`. Do not put it in PHASE_A_IDENTITY_KEYS, because that set is automatically granted trusted routing update/removal authority. The new key must NOT belong to TRUSTED_ROUTING_EFFECT_KEYS, TRUSTED_ROUTING_REMOVAL_KEYS or provider control-intent keys. Existing prepared-result ownership/attestation checks must therefore reject provider updates, queued updates, ordinary removals, trusted routing updates/removals and forged/tampered prepared envelopes involving the field. Even an identical provider echo is not provider ownership. Reuse existing checks; no second attestation system or prose rule.

**StateStore initialization:** Extend the existing `SquadStateStore.initialize` signature with a trailing `managed_identity: dict[str, str] | None = None`. Existing positional/default calls remain valid and legacy initial JSON does not gain the key. A non-None supplied record is explicitly controller-supplied initialization metadata, not a ledger enrollment operation. Validate before persistence, require record.run_id equals the requested run_id, and derive initial_state.spec_id from the record because initialize has no spec_id argument. Do not infer or overwrite a mismatching supplied run ID.

On reinitialization of the SAME stored managed run, preserve its exact existing record and canonical spec_id automatically when managed_identity is omitted/None; this is deliberate initializer preservation of already owned metadata, not acceptance of missing external authority. A supplied identical record is allowed. A different supplied record, changed run ID, or malformed retained managed record rejects before durable state or backup changes. Never create a replacement run in the same state store by discarding the managed key. No default argument activates a legacy run. Explicit non-None initialization may add the record to an otherwise legacy/empty state only through initialize, never through ordinary save/update paths; the actual durable enrollment/freshness authorization remains the future caller's responsibility.

Select and validate preserved/supplied metadata under initialize's SAME existing exclusive state lock as persistence, not in a pre-lock read with a race. The initial state must retain existing timestamp/autonomy/repair/checkpoint defaults. Keep source/identity database access outside this module and lock. Default legacy call shapes in SquadController need no new keyword and must stay unchanged; preserving inside initialize ensures its existing prepared-identity whitelist cannot silently drop a retained managed record.

**State load and every save:** `_load_unlocked` must validate a present managed record and its spec/run association without repairing or stripping it. `_save_unlocked` remains the single writer. Before changing state bytes, backup bytes or creating a replacement temp file, compare a valid retained record against the desired state: reject removal, replacement or changed run/spec identity; same record with unrelated ordinary changes remains valid. A previously malformed managed field cannot be removed to turn the state legacy. Reject introducing a new managed field through ordinary save, exact-save, prepared routing, recovery or arbitrary controller update paths. Only initialize's narrow internal initialization path may add it, after its validation above. Follow the existing explicit human-input-write authorization pattern for an internal initializer-only flag if needed; do not grant generic routing authority.

Keep the new validation in a focused helper, normalize failures to the existing bounded state-contract error family with json_path `$.managed_identity`, and suppress untrusted record text/cause. Preserve BaseException and existing pre/post-replace durability error semantics. Do not weaken state-revision CAS, lock rank, exact-write readback, human-input authority or unrelated monotonicity rules.

If a prior state file is malformed JSON, managed initialization must fail rather than treat it as empty. Preserve existing legacy behavior for calls without managed metadata where it cannot be established that the old file was managed; do not use substring searches as authority. Missing/deleted/wholly corrupted metadata outside this state protocol cannot be fully detected without the durable registry. This task does not add that runtime lookup and must document the limitation, not claim downgrade resistance against arbitrary external file deletion or a missing database.

**Required first regression before production:** Use a real managed genesis receipt, then reach the missing initialize parameter. The secure-POSIX fixture is module-local in existing source/managed tests: explicitly reuse or define that capability-scoped fixture before running this regression; do not apply it to pure record tests.

```python
def test_initialize_accepts_real_managed_genesis(tmp_path, secure_posix):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_managed import ManagedIdentityRequest
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_state import SquadStateStore
    root = tmp_path.resolve()
    squad = root / "runs/first"
    (squad / "specs/demo").mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(root, squad, "7" * 32).seal()
    with prepared.inspect_sources(tree_paths=("runs/first/specs/demo",), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    authority = IdentityStore.initialize(root)
    source = authority.register_source_context(spec_id="demo", context_id="first-source",
        operation_id="source-registration", manifest=manifest)
    request = ManagedIdentityRequest(source["workspace_uuid"], source["epoch_uuid"],
        "first", "first-source", "runs/first/specs/demo", "source-registration", manifest.sha256)
    genesis = authority.register_managed_identity(spec_id="demo", operation_id="managed-registration",
        request=request)
    state = SquadStateStore(squad)
    state.initialize(run_id="first", mode="greenfield", user_message="game", token_budget=1000,
        entry_phase="phase0-discovery", managed_identity=genesis)
    assert state.load()["managed_identity"] == genesis
    assert state.load()["spec_id"] == "demo"
    assert authority.managed_identity(spec_id="demo") == genesis
```

- [ ] Obtain the actual missing-keyword RED after successful real capture/source/genesis registration; notify root before production. Implement focused validator/reserved field/initializer/writer path, then GREEN. Do not fake the first receipt or fail on an earlier missing import.
- [ ] Independent closed record expectations; malformed/deleted/extra/type/UUID/path/hash/version cases, detached copies, bounded errors/BaseException and no I/O in pure validation. Legacy absent field remains absent; false/None/empty/partial present fields fail.
- [ ] Real state persistence and reopen: identical metadata survives ordinary save, exact save, successful prepared routing and reinitialization; removal, replacement, run/spec changes and ordinary field introduction fail with exact original state AND backup bytes retained. Explicit initialization validates run ID, supplies spec_id, preserves same-run existing metadata under one lock and rejects differing records. A fresh legacy initializer remains byte-shape compatible apart from existing timestamps/revisions.
- [ ] Test ordinary/provider/queued/trusted/control update and removal attempts through existing real preparation/routing APIs, including tampered frozen attestations. Do not merely assert constant membership. Verify guided/semi/banzai initialization/preservation and rejection use the same rules, including before feature_branch exists. No role/quality-debt waiver or extra role.
- [ ] Add `test_managed_identity_prepared_initialization_survives_controller_fresh_start` to the existing simulated-provider controller integration module, using its real fixture/owner setup. It must pass through the actual fresh-start initialization path with retained metadata and show the existing whitelist does not erase it. No real provider calls or production controller changes; if this reveals a required owner change beyond initialize, report the concrete failure to root before changing scope. Manual existing-state replay updates should retain metadata; attempts to inject/replace it via initial_state_updates reject before provider dispatch. Test through existing owner paths where practical and distinguish state preservation from physical source-isolation authority.
- [ ] Real fault and race tests preserve existing CAS and pre/post-replace outcomes: validation failure before any backup/temp write, save failure before replace retains old metadata, after-replace uncertainty reopens to the exact same immutable record, two writers from one revision cannot overwrite metadata or reset run identity. No database/namespace/source checks under state lock; test with explicit I/O/authority tripwires scoped to the new validator paths.
- [ ] Cover malformed retained field/load and malformed prior JSON during managed initialization without overwriting it. Document that complete external state deletion/unknown legacy malformed files require the future durable-registry gate and are not solved by this layer. Do not introduce a heuristic repair or unrelated all-legacy parse-policy change.
- [ ] Final covering run once: tests/unit/test_element_identity_state.py; tests/kernel/test_squad_state.py; tests/kernel/test_prepared_phase_result.py; tests/unit/test_state_transaction_namespace.py; tests/unit/test_element_identity_managed.py; and only tests/integration/test_squad_controller.py::test_managed_identity_prepared_initialization_survives_controller_fresh_start plus any additional named controller tests actually added for this task. Do not run the entire large unchanged controller integration module. No capacity/full-unit/live/provider/install/postcommit repeats. Report exact code point if later self-review fixes need narrower reruns.
- [ ] Self-review write/backup ordering, initializer atomic preservation, ownership namespace closure, compatibility and honest layer limits. Run diffcheck, document, commit all task/report files and return DONE only after completion. Root owns independent full original-base review.

## Remaining integration

The durable registry must still be consulted by trusted startup/dispatch/completion owners, including detection of removed metadata, missing authority and unsupported old schemas. This field does not authenticate a supplied genesis receipt, current physical source scope, a subsequent run transition or semantic judgment. Candidate isolation, producer reservations, exact source/identity/graph completion and bounded repair remain required before activation. No live initialization caller is changed to supply managed_identity by this task.
