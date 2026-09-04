# RE v2 Bounded L3 Source Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make new L3 audits use bounded source-overview contexts, preflight every L3 audit context before provider spend, and durably block old oversized runs with an actionable successor command.

**Architecture:** Preserve protocol `2.5` behavior and add corrected embedded layer protocol `2.5.1` inside schema-5/protocol-2.6. Keep domain work identities exact, change only source projection, and add protocol-2.5-owned preflight authority because the shared failure receipt requires a real dispatch.

**Tech Stack:** Python 3.11+, frozen dataclasses, canonical JSON, content-addressed objects, append-only event/ledger protocols, pytest, shared Rich RE UI.

**Spec:** `docs/superpowers/specs/2026-09-01-re-v2-bounded-l3-source-audit-design.md`

## Global Constraints

- Protocols 2.0-2.4 and existing protocol-2.5 bytes remain unchanged.
- New L3 manifests use `2.5.1`; existing `2.5` manifests retain monolithic source semantics.
- Domain plans, targets, templates, work items, artifact keys, and candidates remain byte-identical.
- Source required closure and final roots still bind all selected domains.
- Preflight finishes for every target before new L3 provider spend.
- Failed preflight records no dispatch, reservation, usage, source text, credentials, or provider stderr.
- Do not modify digest-bound `protocol_25/artifacts.py`, `cli_provider.py`, `runtime.py`, or `controller.py`.
- Preserve all OptaSearch stashes and require clean sources.

---

### Task 1: Version and request identity compatibility

**Files:**
- Modify: `src/harness/re_v2/model.py:19`
- Modify: `src/harness/re_v2/protocol_25/model.py:119-180`
- Modify: `src/harness/re_v2/protocol_25/lifecycle.py:176-455,900-1030`
- Modify: `src/harness/re_v2/protocol_26/model.py:45-130`
- Test: `tests/unit/test_re_v2_protocol_25_model.py`
- Test: `tests/unit/test_re_v2_protocol_25_lifecycle.py`
- Test: `tests/unit/test_re_v2_run_store.py`
- Test: `tests/unit/test_re_v2_protocol_26_model.py`

**Interfaces:**
- Consumes: `RunManifestV4`, `semantic_request_id_v2`, schema-5 layer decoding.
- Produces: `SemanticLayerProtocolV1 = Literal["2.5", "2.5.1"]`; `semantic_request_id_v3` with every keyword-only argument from `semantic_request_id_v2` plus `engine_protocol_version: SemanticLayerProtocolV1`; new epochs default to `2.5.1`, guided successors retain their parent version.

- [ ] **Step 1: Write failing version tests**

```python
def test_manifest_accepts_only_supported_layer_versions() -> None:
    corrected = replace(manifest_v4(), engine_protocol_version="2.5.1")
    assert RunManifestV4.from_json_dict(corrected.to_json_dict()) == corrected
    with pytest.raises(Protocol25SchemaError):
        replace(manifest_v4(), engine_protocol_version="2.5.2")

def test_request_v3_binds_layer_protocol() -> None:
    assert _request_v3("2.5") != _request_v3("2.5.1")
```

Also round-trip schema-5 with embedded `2.5.1` and retain the v2 golden hash.

- [ ] **Step 2: Run tests and see the expected failure**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_model.py tests/unit/test_re_v2_protocol_25_lifecycle.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_26_model.py
```

Expected: `2.5.1` and request-v3 are unsupported.

- [ ] **Step 3: Implement the closed version boundary**

```python
SemanticLayerProtocolV1 = Literal["2.5", "2.5.1"]
_SEMANTIC_LAYER_PROTOCOLS = frozenset({"2.5", "2.5.1"})
```

Validate by membership, extend schema-4 and embedded schema-5 decoding, and add request schema 3 containing every v2 authority field plus `engine_protocol_version`. Keep `semantic_request_id_v2` unchanged.

- [ ] **Step 4: Run Step 2 and verify PASS**

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/model.py src/harness/re_v2/protocol_25/model.py src/harness/re_v2/protocol_25/lifecycle.py src/harness/re_v2/protocol_26/model.py tests/unit/test_re_v2_protocol_25_model.py tests/unit/test_re_v2_protocol_25_lifecycle.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_26_model.py
git commit -m "feat(re): version bounded L3 audit contract"
```

### Task 2: Bounded source graph and exact domain identity

**Files:**
- Modify: `src/harness/re_v2/protocol_25/graph.py:520-665`
- Test: `tests/unit/test_re_v2_protocol_25_graph.py`
- Test: `tests/integration/test_re_v2_protocol_25_recovery.py`

**Interfaces:**
- Consumes: pinned layer version.
- Produces: `_source_audited_template_ids(manifest: RunManifestV4, source_overview: WorkTemplateV2, domain_baselines: tuple[WorkTemplateV2, ...]) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing golden-byte tests**

Compare canonical domain plan, target, template, and work-item bytes between versions. Then assert:

```python
assert corrected_source.audited_template_ids == (source_overview_id,)
assert corrected_source.required_template_ids == legacy_source.required_template_ids
assert corrected_source.coverage == legacy_source.coverage
```

Add a partial-selection test retaining `selected-domains` coverage.

- [ ] **Step 2: Run and see corrected sources still include domain baselines**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_graph.py tests/integration/test_re_v2_protocol_25_recovery.py -k 'graph or audit_dispatch_authority'
```

- [ ] **Step 3: Branch only source audited IDs**

```python
if manifest.engine_protocol_version == "2.5.1":
    audited_template_ids = (source_overview.template_id,)
else:
    audited_template_ids = tuple(sorted((source_overview.template_id, *domain_ids)))
```

Do not alter required closure, target materialization, policies, executors, or runtime.

- [ ] **Step 4: Run Step 2 and verify PASS**

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_25/graph.py tests/unit/test_re_v2_protocol_25_graph.py tests/integration/test_re_v2_protocol_25_recovery.py
git commit -m "feat(re): bound L3 source audit projection"
```

### Task 3: Typed preflight authority and replay

**Files:**
- Create: `src/harness/re_v2/protocol_25/preflight.py`
- Modify: `src/harness/re_v2/protocol_25/events.py:20-250,270-390,760-800`
- Modify: `src/harness/re_v2/protocol_25/ledger.py:1-180,620-820`
- Test: `tests/unit/test_re_v2_protocol_25_preflight.py`
- Test: `tests/unit/test_re_v2_protocol_25_events.py`
- Test: `tests/unit/test_re_v2_protocol_25_ledger.py`

**Interfaces:**
- Produces: `AuditContextPreflightEntryV1`, `AuditContextPreflightFailureV1`, `AuditContextPreflightResultV1`; replay completion/failure fields; ledger `audit_context_preflight_failures`.

- [ ] **Step 1: Write failing closed-schema tests**

```python
failure = AuditContextPreflightFailureV1(
    schema_version=1,
    audit_target_id=digest("target"),
    work_item_id=digest("work"),
    scope_kind="source",
    source_id="pressbox-search-soccer-api",
    domain_key=None,
    reason_code="semantic_context_byte_ceiling_exceeded",
    projection_class="semantic-audit-context",
    measured_canonical_json_bytes=2_701_823,
    max_canonical_json_bytes=196_608,
    provider_dispatch_count=0,
)
assert AuditContextPreflightFailureV1.from_json_dict(failure.to_json_dict()) == failure
```

Reject unknown fields/reasons, nonzero dispatch count, invalid scope pairs, and ceiling failures where measured bytes do not exceed allowed bytes.

- [ ] **Step 2: Write failing event and ledger tests**

Test exact closed payloads for `audit_context_preflight_completed` with ordered target/context-hash/byte entries and `audit_context_preflight_failed` with target, work item, receipt, reason, measured/allowed bytes, and zero dispatches. Require one result at most and round-trip `audit_context_preflight_failure` in the semantic ledger.

- [ ] **Step 3: Run tests and verify failure**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_preflight.py tests/unit/test_re_v2_protocol_25_events.py tests/unit/test_re_v2_protocol_25_ledger.py
```

- [ ] **Step 4: Implement values, event replay, and ledger replay**

Use frozen slot dataclasses with exact `FIELDS`, `to_json_dict`, `from_json_dict`, and content-digest identity. Use controlled reasons:

```python
PreflightReasonV1 = Literal[
    "semantic_context_byte_ceiling_exceeded",
    "audit_target_authority_invalid",
    "immutable_object_missing",
    "immutable_object_hash_mismatch",
    "snapshot_evidence_invalid",
    "response_schema_authority_invalid",
    "semantic_context_projection_invalid",
]
```

The failure type has no dispatch/capture/candidate/usage authority. Add both events to semantic replay. Allow a legacy `2.5` recovery preflight after accepted audits, but reject a second result. Add the failure decoder, state, view, idempotent record, and facade method to the protocol-2.5 ledger.

- [ ] **Step 5: Run Step 3 and verify PASS**

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_25/preflight.py src/harness/re_v2/protocol_25/events.py src/harness/re_v2/protocol_25/ledger.py tests/unit/test_re_v2_protocol_25_preflight.py tests/unit/test_re_v2_protocol_25_events.py tests/unit/test_re_v2_protocol_25_ledger.py
git commit -m "feat(re): add durable L3 context preflight authority"
```

### Task 4: All-target preflight and durable failure lifecycle

**Files:**
- Modify: `src/harness/re_v2/protocol_25/preflight.py`
- Modify: `src/harness/re_v2/protocol_25/recovery.py:40-210,443-620,1507-1565`
- Test: `tests/unit/test_re_v2_protocol_25_preflight.py`
- Test: `tests/integration/test_re_v2_protocol_25_recovery.py`
- Test: `tests/integration/test_re_v2_protocol_25_controller.py`

**Interfaces:**
- Produces: `preflight_audit_contexts(context) -> AuditContextPreflightResultV1`; `ensure_audit_context_preflight(context) -> AuditContextPreflightResultV1`.

- [ ] **Step 1: Write failing zero-call and crash-recovery tests**

Create an oversized source context. Assert no provider call or new `dispatch_leased` event, unique failure receipt/event, terminal `run_failed`, exact sizes, and failed target state. Add missing-object and corrupt-snapshot cases with distinct reasons. Inject faults after object publication, failure receipt, failed event, and terminal event; continuation must converge without provider work.

- [ ] **Step 2: Run tests and verify failure**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_preflight.py tests/integration/test_re_v2_protocol_25_recovery.py tests/integration/test_re_v2_protocol_25_controller.py -k 'preflight or audit_action'
```

- [ ] **Step 3: Factor a pure projection seam**

```python
def _project_audit_dispatch_authority(
    context: Protocol25RunContext,
    audit_target_id: str,
) -> tuple[WorkItemV2, SemanticContextV1, bytes]:
    ledger = context.ledger.replay()
    accepted = _accepted_prerequisites(context, ledger)
    materialized = context.semantic_graph.ready_audit_targets(accepted)
    selected = tuple(
        (target, template)
        for target, template in zip(
            materialized,
            context.semantic_graph.audit_templates,
            strict=True,
        )
        if target.audit_target_id == audit_target_id
    )
    if len(selected) != 1:
        raise Protocol25RecoveryError("audit target is not uniquely ready")
    target, template = selected[0]
    dependencies = {
        template_id: accepted[template_id]
        for template_id in template.required_template_ids
    }
    item = context.semantic_graph.instantiate_audit_item(
        template, target, dependencies
    )
    lower_hashes = tuple(sorted({
        *(authority.artifact_hash for authority in target.audited_artifacts),
        *target.lower_dependency_hashes,
        *target.context_object_hashes,
        *target.evidence_object_hashes,
    }))
    payloads = {
        object_hash: context.object_store.read_blob(object_hash)
        for object_hash in lower_hashes
    }
    semantic_context = context.semantic_runtime.build_audit_context(
        audit_target=target,
        workspace_partition=context.semantic_inputs.workspace_partition,
        authority_payloads=payloads,
    )
    context_bytes = canonical_json_bytes(semantic_context.to_json_dict())
    return item, semantic_context, context_bytes
```

Make `build_audit_dispatch_authority` persist the returned bytes. For ceiling measurement without changing digest-bound `runtime.py`, use a temporary copied policy with a deterministic high ceiling, rebuild, restore the original ceiling value in the serialized dictionary, and measure canonical bytes. Never persist that measurement-only context.

- [ ] **Step 4: Implement all-or-nothing publication**

Project every ready target in stable graph order into memory. On success, write exact context blobs and append one completion event. On failure, write typed receipt, append failure event, and apply `terminal_blocked_incomplete`. Replay-check each suffix for idempotence. Invoke before each `audit_target`; an old run with accepted audits but no result preflights before its next pending target. A replayed failure sets controller `work_item_failed=True` and marks the target failed.

- [ ] **Step 5: Run Step 2 and verify PASS**

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_25/preflight.py src/harness/re_v2/protocol_25/recovery.py tests/unit/test_re_v2_protocol_25_preflight.py tests/integration/test_re_v2_protocol_25_recovery.py tests/integration/test_re_v2_protocol_25_controller.py
git commit -m "fix(re): preflight L3 contexts before provider dispatch"
```

### Task 5: Actionable status and telemetry

**Files:**
- Modify: `src/harness/re_v2/protocol_25/status.py:120-220,330-410,598-710`
- Modify: `src/harness/re_v2/protocol_26/status.py`
- Modify: `src/echelon/re_ui.py`
- Test: `tests/unit/test_re_v2_protocol_25_status.py`
- Test: `tests/unit/test_re_v2_protocol_26_status.py`
- Test: `tests/unit/test_re_ui.py`
- Test: `tests/integration/test_re_v2_protocol_25_cli.py`

**Interfaces:**
- Produces: additive JSON `layer_protocol_version`, `preflight`, and `telemetry.provider_dispatches_avoided_by_preflight`; shared card renders the blocker and exact successor command.

- [ ] **Step 1: Write failing status tests**

Assert `blocked_incomplete`, scope/reason/sizes, zero dispatches, outer/embedded versions, and an exact `echelon re deepen --to L3 --all --from-run re-20260830-155816-918918` action for the all-source fixture. Assert identical `continue` is absent. Verify the Rich card shows `no provider call` and the copyable command.

- [ ] **Step 2: Run tests and verify failure**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_status.py tests/unit/test_re_v2_protocol_26_status.py tests/unit/test_re_ui.py tests/integration/test_re_v2_protocol_25_cli.py -k 'status or preflight'
```

- [ ] **Step 3: Implement additive status and UI**

Build status only from durable replay/ledger authority. Include selected/checked counts, maximum/allowed bytes, failed scope/reason, and avoided dispatch count. Resolve the original lower analysis parent and selection for the corrected successor command. Render through `re_ui.py`, not a protocol-specific formatter.

- [ ] **Step 4: Run Step 2 and verify PASS**

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_25/status.py src/harness/re_v2/protocol_26/status.py src/echelon/re_ui.py tests/unit/test_re_v2_protocol_25_status.py tests/unit/test_re_v2_protocol_26_status.py tests/unit/test_re_ui.py tests/integration/test_re_v2_protocol_25_cli.py
git commit -m "feat(re): report L3 preflight blockers and recovery action"
```

### Task 6: Corrected CLI creation and checkpoint reuse

**Files:**
- Modify: `src/echelon/cli.py:12370-12530,15520-15720,16360-16680`
- Modify: `src/harness/re_v2/protocol_26/reconstruction.py:360-450`
- Test: `tests/unit/test_cli_re_v2_protocol_25.py`
- Test: `tests/unit/test_cli_re_v2_protocol_26.py`
- Test: `tests/unit/test_re_v2_protocol_26_reconstruction.py`
- Test: `tests/integration/test_re_v2_protocol_26_cli.py`
- Test: `tests/integration/test_re_v2_protocol_26_adoption.py`

**Interfaces:**
- Produces: new L3 and automatic L4 prerequisites embed `2.5.1`; origin reconstruction adopts exact compatible domain candidates only.

- [ ] **Step 1: Write failing creation/adoption tests**

Assert new L3 and automatic L4 prerequisite manifests embed `2.5.1`. Build a legacy blocked sibling with accepted domain/source candidates and assert the corrected child selects the exact domain work ID, rejects the legacy source work ID, and has distinct source work/request IDs. Mutate policy, executor, target, work item, and certification independently and assert rejection.

- [ ] **Step 2: Run tests and verify failure**

```bash
pytest -q tests/unit/test_cli_re_v2_protocol_25.py tests/unit/test_cli_re_v2_protocol_26.py tests/unit/test_re_v2_protocol_26_reconstruction.py tests/integration/test_re_v2_protocol_26_cli.py tests/integration/test_re_v2_protocol_26_adoption.py
```

- [ ] **Step 3: Emit corrected authority and preserve exact reconstruction**

Pass `engine_protocol_version="2.5.1"` from `_prepare_re_v25_creation`. Keep the existing four-module L3 implementation digest. Reconstruct checkpoint work with the origin's pinned manifest; compare full work/certification identity and never remap a source candidate.

- [ ] **Step 4: Run Step 2 and verify PASS**

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py src/harness/re_v2/protocol_26/reconstruction.py tests/unit/test_cli_re_v2_protocol_25.py tests/unit/test_cli_re_v2_protocol_26.py tests/unit/test_re_v2_protocol_26_reconstruction.py tests/integration/test_re_v2_protocol_26_cli.py tests/integration/test_re_v2_protocol_26_adoption.py
git commit -m "feat(re): reuse exact domain audits in bounded L3 runs"
```

### Task 7: Compatibility, installation, and real OptaSearch proof

**Files:**
- Verify: all RE v2 unit/integration tests
- Verify workspace: `/Users/michalbachorik/work/optasearch`
- Verify forensic run: `re-20260901-110701-757460`

**Interfaces:**
- Produces: installed proof that the old run blocks with zero calls and corrected all-source L3 preflights below 196,608 bytes before advancing toward L4.

- [ ] **Step 1: Run protocol and full suites**

```bash
pytest -q tests/unit/test_re_v2*.py tests/unit/test_cli_re*.py
pytest -q tests/integration/test_re_v2*.py
pytest -q
python -m compileall -q src
git diff --check
```

Expected: PASS; list environment skips exactly.

- [ ] **Step 2: Verify digest-bound modules were not changed**

```bash
git diff --name-only a7290543..HEAD
```

Expected: `protocol_25/artifacts.py`, `cli_provider.py`, `runtime.py`, and `controller.py` are absent.

- [ ] **Step 3: Install the checkout**

```bash
bash scripts/install.sh
echelon --version
```

- [ ] **Step 4: Verify OptaSearch and all sources are clean**

Record `git status --short` and `git stash list` before testing. If any source is dirty, stop and recommend commit/stash/revert. Do not change or expose stash contents.

- [ ] **Step 5: Continue the forensic run once**

```bash
cd /Users/michalbachorik/work/optasearch
echelon re continue re-20260901-110701-757460
echelon re status re-20260901-110701-757460 --json
```

Expected: durable blocker, exact context reason/sizes, unchanged provider dispatch count, and corrected deepen command rather than identical continuation.

- [ ] **Step 6: Start or reuse corrected all-source L4 deepening**

```bash
echelon re deepen --to L4 --all --from-run re-20260830-155816-918918
```

Expected: distinct corrected L3 prerequisite, embedded `2.5.1`, 81/81 contexts preflighted below 196,608 bytes, compatible domain/lower checkpoints adopted, and monolithic source candidates rejected.

- [ ] **Step 7: Monitor to the authorized terminal boundary**

Use `echelon re status <corrected-run-id>`. If authorization pauses, report the absolute required total and exact continuation command without increasing it. If L3 completes, verify automatic L4 advance.

- [ ] **Step 8: Verify workspace and stashes are unchanged**

Repeat the clean/status and stash metadata checks from Step 4 and compare exactly.

## Self-Review Record

- Spec coverage: Tasks 1-7 cover versioning, exact domain identity, bounded sources, closure, preflight, durable blockers, status, adoption, installation, and real-workspace proof.
- Placeholder scan: `<corrected-run-id>` is a runtime-observed command result, not an undecided implementation.
- Type consistency: `AuditContextPreflightEntryV1`, `AuditContextPreflightFailureV1`, `AuditContextPreflightResultV1`, `semantic_request_id_v3`, and `engine_protocol_version` are consistent.
- Design correction: protocol-2.5 owns zero-dispatch failure authority and corrected semantic request identity explicitly binds the layer version.
