# RE v2 L3 Semantic Audit and Bounded Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship protocol 2.5 as an opt-in `echelon re deepen --to L3` child-run workflow that audits exact accepted L0/L1/L2 authority, freezes one stable semantic finding epoch, and performs bounded overlay-based closure without mutating lower layers.

**Architecture:** Add a focused `harness.re_v2.protocol_25` package over the existing protocol-2.2 durability/execution substrate and the immutable protocol-2.4 L2 child-run contract. Schema 4 pins audit scope, mode, lineage, parent authority, policy, semantic resources, optional guidance, and epoch authority. New L3 values use existing `ArtifactKeyV2`, object/candidate/event/ledger envelopes, Prosaic prompt loading, and shared coding-provider execution. Only schema routing and deliberately generic shared seams change; no protocol-2.2 installed-authority source and no protocol-2.4 source changes.

**Tech Stack:** Python 3.11+, standard-library dataclasses/json/fcntl/os/pathlib, existing PyYAML/jsonschema/Typer/pytest dependencies, Prosaic metadata loading, `SquadCliProvider`, and the existing RE v2 content-addressed object, event, ledger, execution-capture, budget, recovery, and materialization primitives.

**Spec:** `docs/superpowers/specs/2026-08-25-re-v2-l3-semantic-audit-closure-design.md`

## Global Constraints

- Protocol 2.5 uses manifest schema 4. Protocols 2.0/2.1 retain schema 1, 2.2/2.3 retain schema 2, and 2.4 retains schema 3 with identical canonical bytes and behavior.
- Treat every file under `src/harness/re_v2/protocol_24/` as frozen. In particular, changing `artifacts.py`, `runtime.py`, or `controller.py` changes the protocol-2.4 installed implementation digest and can strand existing L2 runs.
- Do not modify protocol-2.2 installed-authority sources: `baseline.py`, `cli_provider.py`, `context.py`, `controller.py`, `evidence.py`, `execution.py`, `inventory.py`, `partition.py`, `provider.py`, `response_schemas.py`, or `runtime.py`.
- The layer chain is additive `L0 -> L1 -> L2 -> L3`. An L1 parent schedules missing selected L2 work through imported protocol-2.4 producers before any audit target becomes ready.
- Accepted L0/L1/L2 artifacts and receipts are adopted exactly. Semantic repair creates L3 overlays keyed by existing `ArtifactKeyV2`; it never edits, replaces, or recertifies a lower-layer object.
- Every model-backed audit, resolution, recheck, and source guard loads neutral Prosaic bytes and executes through the existing shared CLI provider path. Add no adapter, transport, credential path, provider-specific result protocol, or model-selection branch.
- `echelon.re-validator` keeps its existing v1 contract and gains only explicit bounded v2 modes. `echelon.re-resolver` is a neutral Prosaic role. Both use paired ALWAYS/NEVER rules.
- Audit targets have at most two external dispatches total. Resolution, recheck, and source-guard operations have the same two-dispatch maximum; retry categories cannot stack into a third call.
- Initial audit calls consume run-wide resources but no semantic round. Resolution/recheck/source-guard calls consume run-wide and semantic token/time pools. One completed source cycle increments each participating target exactly once.
- Fixed policy limits are three semantic rounds per target, two consecutive no-reduction rounds, two provider attempts per operation, and one shared contract retry. Resource authorization cannot raise these limits.
- Finding identity uses only controller-issued target/rule/class/subject/claim/evidence/audited-hash authority. Diagnostic prose, ordering, run ID, timestamps, and projection state never enter finding or epoch identity.
- Closure output cannot add work to the frozen epoch. Normalized deferred observations require an explicit next epoch and prevent the current child from claiming L3 complete.
- Exact request and exact guidance reuse an existing child with zero provider calls. Completed or blocked parents remain immutable; continuation only authorizes resources on a paused child, while guidance creates a successor.
- Source preflight remains clean-Git only. All provider context comes from the immutable snapshot and run-local accepted authority; provider candidate roots remain isolated.
- Materialize only below `runs/<run-id>/re/l3/`. Do not run workspace synthesis, write workspace `re/`, publish source artifacts, implement L4, or introduce atomic lower-artifact repair.
- No new third-party runtime dependency is introduced.

## File Structure

Create protocol-2.5 authority and orchestration modules without editing protocol 2.4:

```text
src/harness/re_v2/protocol_25/
  __init__.py          protocol/schema constants and exports
  model.py             schema-4 manifest, semantic policy, mode, lineage references
  findings.py          audit targets, finding keys, findings, deferred observations
  artifacts.py         audit candidates, epochs, overlays, assessments, roots
  policies.py          L3 artifact/audit policy and executor catalog composition
  graph.py             L1/L2 adoption, missing-L2 prerequisites, L3 target graph
  adoption.py          ParentAuthorityBundleV2 and mode-specific parent validation
  inputs.py            manifest-last schema-4 input publication/loading
  ledger.py            protocol-2.5 typed receipt facade over DurableLedger
  events.py            protocol-2.5 events and replay over protocol-2.4/shared events
  budget.py            semantic pool and source-cycle progress replay
  runtime.py           candidate normalization, certification, roots, composed views
  controller.py        narrow L3 state machine over Protocol24Controller
  recovery.py          protocol-2.5 durable-boundary reconciliation
  lifecycle.py         child creation, exact reuse, successors, continuation authority
  materialization.py   run-local L3 projection and deterministic rebuild
  status.py            schema-4 status document, telemetry dimensions, banners
```

Add tests at the same boundaries:

```text
tests/re_v2_protocol_25_fixtures.py
tests/unit/test_re_v2_protocol_25_model.py
tests/unit/test_re_v2_protocol_25_findings.py
tests/unit/test_re_v2_protocol_25_artifacts.py
tests/unit/test_re_v2_protocol_25_policies.py
tests/unit/test_re_v2_protocol_25_graph.py
tests/unit/test_re_v2_protocol_25_adoption.py
tests/unit/test_re_v2_protocol_25_inputs.py
tests/unit/test_re_v2_protocol_25_ledger.py
tests/unit/test_re_v2_protocol_25_events.py
tests/unit/test_re_v2_protocol_25_budget.py
tests/unit/test_re_v2_protocol_25_runtime.py
tests/unit/test_re_v2_protocol_25_prosaic.py
tests/unit/test_re_v2_protocol_25_materialization.py
tests/unit/test_re_v2_protocol_25_status.py
tests/unit/test_cli_re_v2_protocol_25.py
tests/integration/test_re_v2_protocol_25_controller.py
tests/integration/test_re_v2_protocol_25_recovery.py
tests/integration/test_re_v2_protocol_25_cli.py
tests/integration/test_re_v2_protocol_25_live.py
```

Modify only additive routers or schema-neutral seams:

```text
src/harness/re_v2/model.py
src/harness/re_v2/run_store.py
src/harness/re_v2/status.py
src/harness/re_v2/protocol_22/model.py
src/harness/re_v2/protocol_22/ledger.py
src/harness/re_v2/protocol_22/recovery.py
src/harness/re_v2/protocol_22/materialization.py
src/echelon/cli.py
src/echelon/cli_app.py
prosaic/subagents/echelon.re-validator.md
prosaic/subagents/echelon.re-resolver.md
CHANGELOG.md
docs/findings/echelon-grounded-review-register.md
```

Before modifying any shared file, prove it is absent from `_re_schema2_installed_registry()` implementation digests and from `_re_v22_implementation_digest()` arguments used by protocol 2.4. If it is pinned, move the extension into `protocol_25` instead.

---

### Task 1: Freeze Compatibility and Register Schema 4

**Files:**
- Create: `src/harness/re_v2/protocol_25/__init__.py`
- Create: `src/harness/re_v2/protocol_25/model.py`
- Create: `tests/re_v2_protocol_25_fixtures.py`
- Create: `tests/unit/test_re_v2_protocol_25_model.py`
- Modify: `src/harness/re_v2/model.py`
- Modify: `src/harness/re_v2/protocol_22/model.py`
- Modify: `src/harness/re_v2/run_store.py`
- Test: `tests/unit/test_re_v2_protocol_compatibility.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces `RunManifestV4`, `SemanticClosurePolicyV1`, and `RunModeV1` values `new-audit-epoch`, `audit-successor`, and `closure-successor`.
- Pins target `L3`, goal `semantic-audit-closure`, run-wide `BudgetPolicyV2`, independent semantic token/time ceilings, fixed semantic limits, exact catalog references, optional epoch/guidance references, and exact semantic request ID.
- Extends the shared additive `LayerV2`/`GoalV2` value validation with `L3`/`semantic-audit-closure` so protocol 2.5 can keep using `ArtifactKeyV2` and `WorkTemplateV2`; old serialized values remain unchanged.
- Dispatches only `(schema_version=4, engine_protocol_version="2.5")` to `RunManifestV4`.

- [ ] **Step 1: Record old canonical authorities before editing**

Run:

```bash
pytest -q tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_run_store.py
git diff --exit-code -- src/harness/re_v2/protocol_22 src/harness/re_v2/protocol_24
```

Expected: compatibility/run-store tests pass; protocol-2.2 and protocol-2.4 source trees are unchanged from `bcb9a56e`.

- [ ] **Step 2: Write failing closed-model and exact-dispatch tests**

```python
def test_manifest_v4_round_trips_canonically() -> None:
    manifest = manifest_v4()
    payload = canonical_json_bytes(manifest.to_json_dict())
    assert RunManifestV4.from_json_dict(json.loads(payload)) == manifest


@pytest.mark.parametrize("field", ["max_rounds_per_target", "plateau_limit"])
def test_semantic_fixed_limits_cannot_be_changed(field: str) -> None:
    raw = semantic_policy_v1().to_json_dict()
    raw[field] = raw[field] + 1
    with pytest.raises(Protocol22SchemaError):
        SemanticClosurePolicyV1.from_json_dict(raw)


def test_schema_4_rejects_every_protocol_except_2_5(tmp_path: Path) -> None:
    raw = manifest_v4().to_json_dict()
    raw["engine_protocol_version"] = "2.4"
    write_canonical_manifest(tmp_path, raw)
    with pytest.raises(ReV2RunStoreError, match="schema/protocol"):
        load_run_manifest(tmp_path)
```

- [ ] **Step 3: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: collection fails because `protocol_25` and `RunManifestV4` do not exist.

- [ ] **Step 4: Implement strict schema-4 values and dispatch**

Use closed dataclasses with `ClassVar FIELDS`, `exact_object`, `safe_id`, `digest_value`, sorted tuple validation, canonical `to_json_dict`, and exact `from_json_dict`, following `RunManifestV3`. Add `RE_V2_SCHEMA_4_PROTOCOLS = frozenset({"2.5"})`, extend the root `Manifest` union, and add exact schema-4 decode/validation branches.

- [ ] **Step 5: Re-run model, store, and frozen-fixture tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all pass; existing schema-1/2/3 canonical digests remain exact.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/model.py src/harness/re_v2/run_store.py \
  src/harness/re_v2/protocol_22/model.py \
  src/harness/re_v2/protocol_25/__init__.py \
  src/harness/re_v2/protocol_25/model.py \
  tests/re_v2_protocol_25_fixtures.py \
  tests/unit/test_re_v2_protocol_25_model.py \
  tests/unit/test_re_v2_protocol_compatibility.py \
  tests/unit/test_re_v2_run_store.py
git commit -m "feat(re-v2): register protocol 2.5 manifest"
```

---

### Task 2: Define Stable Audit and Finding Authority

**Files:**
- Create: `src/harness/re_v2/protocol_25/findings.py`
- Create: `tests/unit/test_re_v2_protocol_25_findings.py`
- Modify: `tests/re_v2_protocol_25_fixtures.py`

**Interfaces:**
- Produces `AuditTargetV1`, `FindingKeyV1`, `SemanticFindingV1`, and `DeferredObservationV1`.
- Uses closed finding classes and controller-issued `rule_id`, `subject_ref`, `claim_anchor_ids`, and `evidence_anchor_ids`.
- Excludes all diagnostic prose from `FindingKeyV1.identity` and includes it only in bounded diagnostic values.

- [ ] **Step 1: Write failing identity and authority-boundary tests**

```python
def test_finding_identity_ignores_diagnostic_rewording() -> None:
    first = semantic_finding(title="Missing retry", explanation="No retry is shown")
    second = semantic_finding(title="Retry absent", explanation="Evidence omits retry")
    assert first.finding_key.identity == second.finding_key.identity
    assert first.identity != second.identity


def test_finding_identity_changes_with_structured_authority() -> None:
    first = finding_key(subject_ref="surface:search")
    second = finding_key(subject_ref="surface:export")
    assert first.identity != second.identity


def test_free_form_subject_is_rejected() -> None:
    with pytest.raises(Protocol22SchemaError, match="controller-issued"):
        finding_key(subject_ref="the API probably retries")
```

Cover unsorted/duplicate anchors, unknown rule/class, unregistered target, evidence outside target closure, oversized prose, NFC/whitespace violations, equivalent evidence-fact aliases, and deterministic deferred-observation IDs.

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_findings.py`

Expected: collection fails because the finding authority types are absent.

- [ ] **Step 3: Implement closed finding normalization**

Keep allowed vocabulary in immutable policy-owned tuples. Require normalization against a controller-created `FindingAuthorityVocabularyV1`; do not accept provider-created IDs. Hash `FindingKeyV1.to_json_dict()` for the key ID and hash the full `SemanticFindingV1` for diagnostic-object identity.

- [ ] **Step 4: Run identity/property tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_findings.py`

Expected: all pass, including reordering/rewording stability and distinct-authority separation.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_25/findings.py \
  tests/re_v2_protocol_25_fixtures.py \
  tests/unit/test_re_v2_protocol_25_findings.py
git commit -m "feat(re-v2): define stable semantic findings"
```

---

### Task 3: Define L3 Artifacts, Assessments, Receipts, and Roots

**Files:**
- Create: `src/harness/re_v2/protocol_25/artifacts.py`
- Create: `tests/unit/test_re_v2_protocol_25_artifacts.py`
- Modify: `tests/re_v2_protocol_25_fixtures.py`

**Interfaces:**
- Produces `AuditCandidateV1`, `AuditEpochV1`, `SemanticResolutionOverlayV1`, `SemanticCertificationReceiptV1`, `TargetClosureAssessmentV1`, `SourceCompositionAssessmentV1`, `FindingClosureReceiptV1`, `AuditClosureRootV1`, and `L3SourceRootV1`.
- Uses existing `ArtifactKeyV2` for `semantic-audit-findings` and L3 resolution overlays.
- Separates structurally accepted attempts from active composed authority; final closure receipts require both target and passing source assessment hashes.

- [ ] **Step 1: Write failing canonical and cross-reference tests**

```python
def test_epoch_identity_is_independent_of_run_and_time() -> None:
    first = audit_epoch_v1(run_metadata=("run-a", "2026-01-01T00:00:00Z"))
    second = audit_epoch_v1(run_metadata=("run-b", "2026-08-26T12:00:00Z"))
    assert first.identity == second.identity


def test_closure_receipt_requires_passing_source_guard() -> None:
    with pytest.raises(Protocol22SchemaError, match="source composition"):
        finding_closure_receipt(source_assessment=source_assessment(outcome="failed"))


def test_resolution_rejects_non_epoch_finding() -> None:
    with pytest.raises(Protocol22SchemaError, match="outside audit epoch"):
        resolution_overlay(finding_ids=(digest("not-in-epoch"),))
```

Also cover exact target/candidate/audited-root binding, null pre-epoch reference, zero-finding epoch, prior-overlay chain, supersession references, assessment coverage exactly once, new-finding rejection, previous closure-receipt dependency, unresolved/root set equality, provisional domain closure, selected coverage, and deferred-observation completion rejection.

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_artifacts.py`

Expected: collection fails because L3 artifact/receipt types are absent.

- [ ] **Step 3: Implement strict immutable value types**

Every type gets an exact closed decoder and content identity. Constructors validate cross-references against explicit epoch/target/source inputs rather than consulting mutable state. `L3SourceRootV1.state` accepts only `complete`, `next_epoch_required`, and `blocked`; `complete` requires zero unresolved findings and zero deferred observations.

- [ ] **Step 4: Run artifact and finding tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_findings.py tests/unit/test_re_v2_protocol_25_artifacts.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_25/artifacts.py \
  tests/re_v2_protocol_25_fixtures.py \
  tests/unit/test_re_v2_protocol_25_artifacts.py
git commit -m "feat(re-v2): define L3 closure authority"
```

---

### Task 4: Compose L3 Policies and Shared Prosaic Execution

**Files:**
- Create: `src/harness/re_v2/protocol_25/policies.py`
- Create: `tests/unit/test_re_v2_protocol_25_policies.py`
- Create: `tests/unit/test_re_v2_protocol_25_prosaic.py`
- Modify: `prosaic/subagents/echelon.re-validator.md`
- Create: `prosaic/subagents/echelon.re-resolver.md`

**Interfaces:**
- Produces a combined exact L0/L1/L2/L3 artifact-policy catalog, closed audit taxonomy, and executor entries for audit, resolution, recheck, and source guard.
- Reuses `SHARED_AI_CLI_ADAPTER_ID`, compact request renderer/capture, shared usage normalizer, reservation calculator, and the configured provider/model/effort path.
- Adds response-schema hashes and Prosaic agent hashes, not provider adapters.
- Reuses `build_deepening_v1_policy_catalog` and `build_deepening_executor_catalog` when an L1 parent needs missing L2 work; protocol 2.5 does not recreate the L2 deepener catalog.

- [ ] **Step 1: Write failing policy and Prosaic tests**

```python
def test_l3_executor_catalog_reuses_shared_cli_adapter() -> None:
    catalog = build_semantic_executor_catalog(parent_executor_catalog(), authorities())
    for family in ("semantic-audit", "semantic-resolution", "closure-recheck", "source-composition-guard"):
        entry = catalog.entry_for(family)
        assert entry.adapter_id == SHARED_AI_CLI_ADAPTER_ID
        assert entry.execution_mode == "cli"
        assert entry.attempt_policy == AttemptPolicyV2(2, 2, 0, 1, 1, 1)


def test_prosaic_roles_are_provider_neutral() -> None:
    for agent_id in ("echelon.re-validator", "echelon.re-resolver"):
        artifact = ProsaicPromptLoader(PROJECT_ROOT).load_subagent(agent_id)
        assert artifact is not None
        assert artifact.metadata["model_tier"] == "strong"
        assert artifact.metadata["effort"] == "high"
        assert not ({"provider", "model", "adapter"} & set(artifact.metadata))
```

Assert validator v1 text remains unchanged outside its new explicit v2 section; modes allow exactly `AUDIT_EPOCH_TARGET` and `CLOSURE_RECHECK`; resolver writes exactly `resolution.json`; frontmatter is neutral and loaded through `ProsaicPromptLoader`; and v2 execution receives no live-workspace path or read authority beyond its controller-created immutable context. Target rechecks and source composition guards both use `CLOSURE_RECHECK`, distinguished by a controller-owned `assessment_kind` value `target` or `source-composition` in the closed request schema.

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_policies.py tests/unit/test_re_v2_protocol_25_prosaic.py`

Expected: failures for missing L3 policy catalog, resolver role, and validator modes.

- [ ] **Step 3: Implement policy/catalog composition**

Build new executor entries by copying the authenticated parent shared adapter/renderer/usage authorities and replacing only agent, response schema, producer policy, and verifier hashes. Pin the fixed semantic attempt/round/plateau values in `SemanticClosurePolicyV1`; never derive them from CLI resource flags.

- [ ] **Step 4: Extend neutral Prosaic roles**

The validator v2 contract reads only the supplied mode, schema, target, epoch/finding set, and bounded context; it writes exactly `audit.json` or `closure.json`. The resolver reads only unresolved frozen IDs and accepted authority; it writes exactly `resolution.json`. Add paired ALWAYS/NEVER rules and prohibit receipts, routing, counters, new findings, live-source discovery, and lower-layer edits.

- [ ] **Step 5: Run Prosaic/provider compatibility tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_policies.py tests/unit/test_re_v2_protocol_25_prosaic.py tests/unit/test_re_v2_protocol_24_prosaic.py tests/unit/test_re_v2_protocol_22_cli_provider.py tests/unit/test_squad_provider.py`

Expected: all pass; Claude, Codex, Copilot, and OpenCode configuration continues through the existing shared provider route.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_25/policies.py \
  prosaic/subagents/echelon.re-validator.md \
  prosaic/subagents/echelon.re-resolver.md \
  tests/unit/test_re_v2_protocol_25_policies.py \
  tests/unit/test_re_v2_protocol_25_prosaic.py
git commit -m "feat(re-v2): register Prosaic semantic roles"
```

---

### Task 5: Build the Ascending L3 Graph and Audit Targets

**Files:**
- Create: `src/harness/re_v2/protocol_25/graph.py`
- Create: `tests/unit/test_re_v2_protocol_25_graph.py`
- Test: `tests/unit/test_re_v2_protocol_24_graph.py`

**Interfaces:**
- Produces `Protocol25Graph` and `build_protocol_25_graph(manifest, inputs, accepted_parent)` using existing `WorkTemplateV2`, `ArtifactKeyV2`, `plan_next_v2`, and protocol-2.4 prerequisite construction.
- Schedules missing selected L2 work before L3, one audit target per selected domain, and one selection-relative source target per selected source.
- Reconstructs adopted accepted authority from the child ledger; it never reads materialized Markdown or parent mutable state.

- [ ] **Step 1: Write failing graph and scope tests**

```python
def test_l1_parent_schedules_missing_l2_before_audit() -> None:
    graph = build_protocol_25_graph(manifest_v4(parent_layer="L1"), inputs_v4(), accepted_l1())
    first = plan_ready(graph, accepted_l1())
    assert first
    assert {item.output_key.layer for item in first} == {"L2"}
    assert not any(item.producer_family == "semantic-audit" for item in first)


def test_domain_selection_adds_domain_and_source_targets() -> None:
    graph = complete_l2_graph(selection=selection(source="api", domains=("search",)))
    assert [(target.kind, target.scope.domain_key) for target in graph.audit_targets] == [
        ("domain", "search"),
        ("source", None),
    ]
    assert graph.source_target("api").coverage == "selected-domains"
```

Cover L2 parent zero prerequisite calls; all-source non-empty domains; deterministic target IDs; exact L2 dependency closure; source cross-domain inputs; `not_requested` unselected domains; no full-source claim for partial selection; empty/unknown domains; and no audit target ready before every exact L2 dependency is accepted.

- [ ] **Step 2: Run graph tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_graph.py`

Expected: collection fails because the protocol-2.5 graph does not exist.

- [ ] **Step 3: Compose, do not copy, prerequisite planning**

Call protocol-2.4 public graph/adoption helpers to reconstruct exact L0/L1/L2 templates and accepted artifacts, then add L3 templates in `protocol_25.graph`. If a required public seam is absent, add a protocol-2.5 adapter over returned values; do not edit protocol-2.4 source.

- [ ] **Step 4: Run L2/L3 graph regressions**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_graph.py tests/unit/test_re_v2_protocol_25_graph.py tests/unit/test_re_v2_protocol_22_graph.py`

Expected: all pass and protocol-2.4 graph fixture identities remain exact.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_25/graph.py \
  tests/unit/test_re_v2_protocol_25_graph.py
git commit -m "feat(re-v2): plan ascending L3 audit work"
```

---

### Task 6: Authenticate ParentAuthorityBundleV2 and Successor Modes

**Files:**
- Create: `src/harness/re_v2/protocol_25/adoption.py`
- Create: `tests/unit/test_re_v2_protocol_25_adoption.py`
- Modify: `tests/re_v2_protocol_25_fixtures.py`

**Interfaces:**
- Produces `ParentAuthorityBundleV2`, embedding unchanged `ParentAuthorityBundleV1` plus authenticated semantic audit/closure authority.
- Produces `validate_protocol_25_parent(...)`, `build_parent_authority_bundle_v2(...)`, and `import_protocol_25_parent_closure(...)`.
- Enforces mode-specific parents: complete L1/L2 for `new-audit-epoch`; pre-epoch `blocked_incomplete` for `audit-successor`; frozen terminal blocker for `closure-successor`; complete or `next_epoch_required` L3 with every frozen finding closed for explicit next epoch.

- [ ] **Step 1: Write failing parent matrix tests**

Cover every accepted mode/state pair and reject running, paused, corrupt, partial, wrong-snapshot, wrong-selection, missing terminal event, incomplete receipt closure, missing candidate, missing epoch/root, cyclic lineage, source commit drift, and dirty Git with exact commit/stash/revert guidance.

```python
@pytest.mark.parametrize(
    ("mode", "parent_state"),
    [
        ("audit-successor", "complete"),
        ("closure-successor", "blocked_incomplete"),
        ("new-audit-epoch", "blocked_plateau"),
    ],
)
def test_mode_rejects_wrong_parent_state(mode: str, parent_state: str) -> None:
    with pytest.raises(Protocol25AdoptionError, match="parent state"):
        validate_protocol_25_parent(parent_run(parent_state), mode=mode)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_adoption.py`

Expected: collection fails because V2 adoption is absent.

- [ ] **Step 3: Implement exact closure import**

Delegate lower-layer validation and `ParentAuthorityBundleV1` construction to protocol-2.4 public functions. Copy authenticated manifest/event/ledger/object closure into child objects once. Add semantic objects and typed receipts in sorted dependency order. Require successful child replay after deleting access to the parent directory.

- [ ] **Step 4: Prove retained partial progress**

Assert an audit successor imports accepted sibling audit candidates and lists only missing target IDs. Assert a closure successor imports the exact epoch, all overlays, assessments, deferred observations, and closed receipts, while only unresolved frozen IDs become work.

- [ ] **Step 5: Run adoption compatibility tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_adoption.py tests/unit/test_re_v2_protocol_25_adoption.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all pass; parent bundles V1 remain byte-identical.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_25/adoption.py \
  tests/re_v2_protocol_25_fixtures.py \
  tests/unit/test_re_v2_protocol_25_adoption.py
git commit -m "feat(re-v2): authenticate L3 successor authority"
```

---

### Task 7: Publish Schema-4 Inputs Manifest Last

**Files:**
- Create: `src/harness/re_v2/protocol_25/inputs.py`
- Create: `tests/unit/test_re_v2_protocol_25_inputs.py`
- Test: `tests/unit/test_re_v2_protocol_24_inputs.py`

**Interfaces:**
- Produces `Protocol25InputSet`, `create_protocol_25_run_store`, and `load_protocol_25_inputs`.
- Publishes workspace partition, artifact policy, executor contract, audit taxonomy/policy, parent bundle, optional frozen epoch, optional guidance, and canonical manifest.
- Reuses the manifest-last/no-clobber input publication primitive extracted for protocol 2.4.

- [ ] **Step 1: Write failing publication and fault tests**

Assert every referenced object is stored/fsynced before `run.json`; optional epoch/guidance presence matches run mode; catalogs authenticate before graph construction; incomplete stores never look runnable; symlinks and existing files fail closed; and each injected failure leaves either no manifest or a fully loadable immutable input set.

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_inputs.py`

Expected: collection fails because schema-4 input storage is absent.

- [ ] **Step 3: Implement schema-4 publication/loading**

Use protocol-2.4's existing schema-neutral publication helper. Validate mode-specific optional fields before publication and again on load. Never recover a missing authority from the parent directory, status JSON, or materialized projection.

- [ ] **Step 4: Run old/new input suites**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_inputs.py tests/unit/test_re_v2_protocol_24_inputs.py tests/unit/test_re_v2_protocol_25_inputs.py`

Expected: all pass with unchanged protocol-2.2/2.4 fixtures.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_25/inputs.py \
  tests/unit/test_re_v2_protocol_25_inputs.py
git commit -m "feat(re-v2): publish schema 4 semantic runs"
```

---

### Task 8: Add Typed Semantic Ledger Authority

**Files:**
- Create: `src/harness/re_v2/protocol_25/ledger.py`
- Create: `tests/unit/test_re_v2_protocol_25_ledger.py`
- Modify: `src/harness/re_v2/protocol_22/ledger.py`
- Test: `tests/unit/test_re_v2_protocol_22_ledger.py`

**Interfaces:**
- Produces `Protocol25LedgerView`, `Protocol25LedgerProtocol`, and `Protocol25Ledger` over the existing `DurableLedger` envelope and `ObjectStore`.
- Recognizes existing protocol-2.2 certification/candidate/acceptance/failure receipts plus protocol-2.5 semantic certification, target/source assessments, closure receipts, audit closure roots, and L3 source roots.
- Keeps `Protocol22Ledger` decoding and record identities unchanged.

- [ ] **Step 1: Write failing append/replay tests**

```python
def test_semantic_ledger_replays_shared_and_l3_receipts(tmp_path: Path) -> None:
    ledger = protocol_25_ledger(tmp_path)
    ledger.record_existing_artifact(accepted_l2_receipt())
    ledger.record_semantic_certification(semantic_certification())
    ledger.record_finding_closure(finding_closure_receipt())
    replayed = ledger.replay()
    assert replayed.accepted_artifacts
    assert replayed.semantic_certifications
    assert replayed.finding_closures


def test_later_closure_receipt_requires_previous_receipt() -> None:
    ledger = populated_epoch_ledger()
    with pytest.raises(ReV2LedgerError, match="preceding receipt"):
        ledger.record_finding_closure(round_two_receipt(previous_receipt_id=None))
```

Cover duplicate IDs, wrong target/epoch, object-hash absence, close-before-assess, source-fail close, non-epoch finding, unresolved/root mismatch, out-of-order round, deferred observation identity, mixed old/new replay, truncation, and hash-chain corruption.

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_ledger.py`

Expected: collection fails because the protocol-2.5 ledger facade is absent.

- [ ] **Step 3: Expose only the generic ledger decoder seam**

If needed, add a schema-neutral registered-receipt decoder hook to `protocol_22/ledger.py` while retaining its default registry and exact behavior. Put every new receipt branch and cross-reference validation in `protocol_25/ledger.py`; do not teach `Protocol22Ledger` L3 semantics.

- [ ] **Step 4: Run ledger and compatibility suites**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_ledger.py tests/unit/test_re_v2_protocol_25_ledger.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all pass; protocol-2.2 ledger fixtures and errors remain exact.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_22/ledger.py \
  src/harness/re_v2/protocol_25/ledger.py \
  tests/unit/test_re_v2_protocol_22_ledger.py \
  tests/unit/test_re_v2_protocol_25_ledger.py
git commit -m "feat(re-v2): persist typed semantic receipts"
```

---

### Task 9: Add Protocol-2.5 Events and Independent Semantic Accounting

**Files:**
- Create: `src/harness/re_v2/protocol_25/events.py`
- Create: `src/harness/re_v2/protocol_25/budget.py`
- Create: `tests/unit/test_re_v2_protocol_25_events.py`
- Create: `tests/unit/test_re_v2_protocol_25_budget.py`
- Test: `tests/unit/test_re_v2_protocol_22_budget.py`
- Test: `tests/unit/test_re_v2_protocol_24_events.py`

**Interfaces:**
- Produces `PROTOCOL_25_EVENTS` by delegating shared and adoption transitions, then validating only L3 event payloads/order.
- Produces `evaluate_semantic_budget`, `SemanticBudgetDecisionV1`, and target progress replay from the existing provider usage/reservation facts.
- Records one target round after a completed source cycle, not per call.
- Derives exactly `running_prerequisites`, `running_audit`, `epoch_frozen`, `running_resolution`, `running_closure_recheck`, `running_source_guard`, `paused_resource`, `blocked_incomplete`, `blocked_plateau`, `next_epoch_required`, or `complete`; no mutable state field independently controls routing.

- [ ] **Step 1: Write failing event ordering tests**

Assert `audit_candidate_accepted` precedes freeze; freeze occurs once after every target; no audit dispatch after freeze; resolution precedes target recheck; all source target assessments precede the source guard; closure receipts follow a passing guard; progress follows receipts; roots precede terminal; terminal immutability; and protocol-2.4 replay rejects L3 events.

- [ ] **Step 2: Write failing budget/progress tests**

```python
def test_audit_does_not_consume_semantic_pool() -> None:
    decision = evaluate_semantic_budget(policy(), events(audit_usage=40_000))
    assert decision.charged_tokens == 0
    assert decision.rounds_by_target == {}


def test_source_cycle_increments_each_participating_target_once() -> None:
    decision = evaluate_semantic_budget(policy(), completed_source_cycle(call_count=7))
    assert decision.rounds_by_target == {DOMAIN_TARGET: 1, SOURCE_TARGET: 1}


def test_runwide_raise_does_not_raise_semantic_limit() -> None:
    decision = authorize(events(), run_tokens=1_000_000, semantic_tokens=None)
    assert decision.semantic_token_limit == policy().semantic_token_limit
```

Cover known/unknown/trusted/reserved usage; token and active-time exhaustion; reduction by unresolved ID set only; prose/overlay changes with same IDs; reset-on-reduction; two-round plateau; absolute third round; and refusal to authorize attempts/rounds/retries/plateau.

Also prove the initial semantic pool reserves one resolution/recheck cycle per selected audit target plus one source guard per selected source through the shared conservative reservation calculator. A later round proceeds only when measured remaining capacity or an explicit semantic resource authorization covers it.

- [ ] **Step 3: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_events.py tests/unit/test_re_v2_protocol_25_budget.py`

Expected: collection fails because protocol-2.5 event/accounting types are absent.

- [ ] **Step 4: Implement delegated replay and semantic projection**

Reuse `EventStore`, `EventProtocol`, shared usage events, and the existing reservation calculator. Add operation class and source-cycle IDs to validated L3 payloads. Derive semantic state, rounds, no-reduction counts, and pool usage from events plus ledger authority; do not store mutable counters.

- [ ] **Step 5: Run shared and semantic event/budget suites**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_budget.py tests/unit/test_re_v2_protocol_24_events.py tests/unit/test_re_v2_protocol_25_events.py tests/unit/test_re_v2_protocol_25_budget.py`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_25/events.py \
  src/harness/re_v2/protocol_25/budget.py \
  tests/unit/test_re_v2_protocol_25_events.py \
  tests/unit/test_re_v2_protocol_25_budget.py
git commit -m "feat(re-v2): bound semantic cycles independently"
```

---

### Task 10: Normalize and Certify Audit, Resolution, and Recheck Candidates

**Files:**
- Create: `src/harness/re_v2/protocol_25/runtime.py`
- Create: `tests/unit/test_re_v2_protocol_25_runtime.py`
- Modify: `src/harness/re_v2/protocol_25/artifacts.py`

**Interfaces:**
- Produces canonical response schemas for `audit.json`, `resolution.json`, and `closure.json` from protocol-2.5 code, leaving protocol-2.2 response schemas unchanged.
- Produces `Protocol25DeterministicRuntime` methods to build bounded contexts; parse candidate output; validate inventory/evidence/IDs; normalize findings and deferred observations; certify semantic artifacts; freeze epochs; and build closure/source roots.
- Reuses candidate capture, `CandidateAssessmentReceiptV1`, `ArtifactAcceptanceReceiptV2`, `PinnedSnapshotReaderV1`, and existing bounded-context/evidence helpers.

- [ ] **Step 1: Write failing response-contract tests**

For audit, require exactly one regular `audit.json`; exact target ID; verdict `PASS` with zero findings or `REPAIR` with at least one; closed rule/class vocabulary; controller-issued anchors; bounded count/bytes; authorized evidence paths/ranges; and no provider-owned IDs, epoch, receipts, routing, counters, or completion.

For resolution, require exactly one regular `resolution.json`; every entry targets one or more currently unresolved IDs; every requested unresolved ID is covered exactly once or explicitly remains unresolved; no sibling/non-epoch ID; controlled disposition; exact supersession/refinement references; and authorized evidence only.

For closure/source guard, require exactly one regular `closure.json`; every input ID appears exactly once; no new authoritative finding; exact overlay/assessment hashes; normalized deferred observations; and no controller-owned receipt or terminal field.

- [ ] **Step 2: Write failing normalization and zero-finding tests**

```python
def test_duplicate_provider_findings_normalize_to_one() -> None:
    result = runtime().certify_audit(candidate_with_reworded_duplicates())
    assert len(result.normalized_findings) == 1


def test_zero_finding_audits_freeze_and_close_without_model_work() -> None:
    epoch = runtime().freeze_epoch(all_pass_candidates())
    closure = runtime().build_closure_root(epoch, receipts=())
    assert epoch.finding_ids == ()
    assert closure.state == "closed"
    assert fake_provider().calls == []
```

- [ ] **Step 3: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_runtime.py`

Expected: collection fails because the protocol-2.5 runtime is absent.

- [ ] **Step 4: Implement bounded contexts and deterministic certification**

Build audit targets from exact accepted artifact/evidence closure. Resolve every provider reference through controller-issued maps before constructing `FindingKeyV1`. Store normalized artifact bytes and semantic certification receipt before acceptance. Keep candidate assessment and artifact acceptance in the shared envelope. Build epochs/roots only from ledger replay, never raw provider output.

- [ ] **Step 5: Implement composed-view and guard inputs**

Compose lower claims plus only the current candidate overlay set in memory. Mark refinement/supersession explicitly. Include already-active closed sibling authority in every source guard. A failed guard leaves implicated authorizing frozen IDs open and does not activate the attempted overlay.

- [ ] **Step 6: Run runtime/artifact/evidence suites**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_runtime.py tests/unit/test_re_v2_protocol_25_artifacts.py tests/unit/test_re_v2_protocol_25_findings.py tests/unit/test_re_v2_protocol_22_evidence.py tests/unit/test_re_v2_protocol_24_artifacts.py`

Expected: all pass; protocol-2.4 artifact identities remain exact.

- [ ] **Step 7: Commit**

```bash
git add src/harness/re_v2/protocol_25/runtime.py \
  src/harness/re_v2/protocol_25/artifacts.py \
  tests/unit/test_re_v2_protocol_25_runtime.py
git commit -m "feat(re-v2): certify frozen semantic candidates"
```

---

### Task 11: Implement the Narrow L3 Controller State Machine

**Files:**
- Create: `src/harness/re_v2/protocol_25/controller.py`
- Create: `tests/integration/test_re_v2_protocol_25_controller.py`
- Test: `tests/integration/test_re_v2_protocol_24_controller.py`

**Interfaces:**
- Produces `Protocol25Controller(Protocol24Controller)` and uses the inherited shared lease/dispatch/capture/commit/retry machinery.
- Specializes protocol-2.5 candidate certification and controller-owned transitions only: audit acceptance, epoch freeze, target resolution, closure recheck, source guard, finding receipt recording, progress/plateau, roots, and terminal state.
- Continues independent audit targets/sources after a sibling exhausts attempts, while preserving every durable accepted sibling result.

- [ ] **Step 1: Write a failing end-to-end fake-executor lifecycle**

```python
def test_controller_freezes_then_closes_one_source() -> None:
    context, provider = l3_context(
        audit_results=(domain_repair(), source_pass()),
        resolution_results=(resolution_for(DOMAIN_FINDING),),
        recheck_results=(closed_assessment(DOMAIN_FINDING),),
        guard_results=(passing_source_guard(),),
    )
    Protocol25Controller(context).run_until_stopped()
    replay = context.ledger.replay()
    assert len(replay.audit_epochs) == 1
    assert replay.latest_closure(DOMAIN_FINDING).verdict == "closed"
    assert replay.l3_source_roots[SOURCE_ID].state == "complete"
    assert context.event_store.replay()[-1].type == "run_completed"
```

- [ ] **Step 2: Add failing bounded-closure cases**

Cover all-pass zero-call closure; one resolver batch per target; one guard per selected source/cycle; closed target skips resolver/recheck but remains in guard context; source-guard regression keeps implicated IDs open; deferred observation produces `next_epoch_required`; reduction resets plateau; unchanged IDs block after two rounds; third-round ceiling; audit contract exhaustion produces `blocked_incomplete`; resource exhaustion pauses; and indeterminate execution is not redispatched.

- [ ] **Step 3: Run controller tests and confirm RED**

Run: `pytest -q tests/integration/test_re_v2_protocol_25_controller.py`

Expected: collection fails because `Protocol25Controller` is absent.

- [ ] **Step 4: Implement controller-owned scheduling**

Subclass `Protocol24Controller` without changing it. Reuse inherited L2 prerequisite execution and shared dispatch functions. Override only candidate filename/schema routing, semantic receipt writes, plan selection after prerequisites, and terminalization. Drive each transition from replayed ledger/events; never trust mutable projection state or model verdict fields.

- [ ] **Step 5: Enforce frozen membership and source-cycle atomicity**

After `audit_epoch_frozen`, reject every audit dispatch. Collect all target assessments for a source cycle before dispatching its source guard. Record final closure receipts in deterministic finding-ID order only after a passing guard. Crash midway through receipt publication must replay to the same complete receipt set without another provider call.

- [ ] **Step 6: Run L2/L3 controller regressions**

Run: `pytest -q tests/integration/test_re_v2_protocol_24_controller.py tests/integration/test_re_v2_protocol_25_controller.py tests/unit/test_re_v2_protocol_25_events.py tests/unit/test_re_v2_protocol_25_ledger.py`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/harness/re_v2/protocol_25/controller.py \
  tests/integration/test_re_v2_protocol_25_controller.py
git commit -m "feat(re-v2): run bounded semantic closure"
```

---

### Task 12: Recover Every L3 Durable Boundary At Most Once

**Files:**
- Create: `src/harness/re_v2/protocol_25/recovery.py`
- Create: `tests/integration/test_re_v2_protocol_25_recovery.py`
- Modify: `src/harness/re_v2/protocol_22/recovery.py`
- Test: `tests/unit/test_re_v2_protocol_22_recovery.py`
- Test: `tests/integration/test_re_v2_protocol_24_recovery.py`

**Interfaces:**
- Produces `Protocol25RunContext`, `recover_protocol_25_run`, and reconciliation helpers over the shared recovery engine.
- Validates manifest, inputs, graph, adopted authority, candidate commits, semantic receipts, events, objects, and snapshot before advancing.
- Never reissues a provider call solely because projection/event/receipt publication after a captured result was interrupted.

- [ ] **Step 1: Parameterize the 16-boundary crash matrix**

Inject a process fault after:

1. audit capture before candidate inventory;
2. audit commit before certification;
3. final audit acceptance before epoch;
4. epoch object before ledger/event;
5. resolution start without observation;
6. resolution capture before inventory;
7. resolution certification before acceptance;
8. overlay acceptance before recheck scheduling;
9. target assessment before source guard;
10. source guard assessment before closure receipts;
11. one of several closure receipts;
12. progress event before next-cycle/plateau projection;
13. all closures before deferred routing/source roots;
14. source roots before terminal event;
15. terminal event before active-pointer repair; and
16. successor input publication before parent adoption completes.

For each boundary, resume twice and assert identical terminal/replay authority, exact dispatch IDs, and no duplicate provider call after durable observation.

- [ ] **Step 2: Run recovery tests and confirm RED**

Run: `pytest -q tests/integration/test_re_v2_protocol_25_recovery.py`

Expected: failures at protocol-2.5 context/recovery routing.

- [ ] **Step 3: Add a registered recovery strategy seam if required**

Keep protocol-2.2 defaults exact. Add only a schema-neutral context callback/strategy entry to `protocol_22/recovery.py` when an inherited method cannot invoke L3 reconciliation. Put semantic boundary logic in `protocol_25/recovery.py`; do not add L3 branches to the pinned controller/execution modules.

- [ ] **Step 4: Implement authoritative reconciliation**

Prefer durable candidate capture, ledger receipts, and event hashes in that order. Reconstruct missing deterministic epoch/root/progress/terminal records idempotently. Classify started-without-observation operations through existing indeterminate execution rules. Rebuild projections, never semantic authority, from replay.

- [ ] **Step 5: Run all protocol recovery matrices**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_recovery.py tests/integration/test_re_v2_protocol_24_recovery.py tests/integration/test_re_v2_protocol_25_recovery.py`

Expected: all pass; no protocol-2.2/2.4 dispatch identity changes.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_22/recovery.py \
  src/harness/re_v2/protocol_25/recovery.py \
  tests/integration/test_re_v2_protocol_25_recovery.py
git commit -m "feat(re-v2): recover semantic closure at most once"
```

---

### Task 13: Add L3 Creation, Exact Reuse, Continue, Resume, and New Epoch CLI

**Files:**
- Create: `src/harness/re_v2/protocol_25/lifecycle.py`
- Create: `tests/unit/test_cli_re_v2_protocol_25.py`
- Create: `tests/integration/test_re_v2_protocol_25_cli.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_cli_re_lifecycle.py`
- Test: `tests/unit/test_cli_re_v2_protocol_24.py`

**Interfaces:**
- Extends `echelon re deepen --to` with `L3` and adds `--semantic-token-limit`, `--semantic-active-ms-limit`, and `--new-audit-epoch`.
- Extends v2 `echelon re continue` with `--re-semantic-token-limit` and `--re-semantic-time-limit-minutes` alongside the existing run-wide controls, and extends v2 `echelon re resume "<answer>"` with immutable successor creation.
- Produces `semantic_request_id_v2(...)`, `guidance_id_for(...)`, exact-child lookup, and creation under the existing workspace lock/pointer sequence.

- [ ] **Step 1: Write failing parser and validation tests**

Cover existing L2 grammar unchanged; required selection; positive semantic limits; semantic flags rejected for L2/v1; `--new-audit-epoch` accepted only for L3 with an eligible terminal L3 parent; `--re-max-inner` rejected for v2; resume answer NFC/size normalization; and exact error text for wrong parent states.

- [ ] **Step 2: Write failing semantic request identity tests**

```python
def test_exact_l3_request_reuses_every_existing_state() -> None:
    for state in ("running_audit", "paused_resource", "blocked_plateau", "next_epoch_required", "complete"):
        workspace = workspace_with_semantic_child(state)
        result = deepen_l3(workspace, exact_original_args())
        assert result.run_id == workspace.existing_child_id
        assert result.provider_calls == 0


def test_changed_guidance_creates_distinct_successor() -> None:
    first = resume(blocked_run(), "Treat timeout as retryable")
    second = resume(blocked_run(), "Treat timeout as terminal")
    assert first.semantic_request_id != second.semantic_request_id
```

Assert request identity binds lineage root, direct parent closure, snapshot/partition, selection, mode, catalogs/policies, accepted audit targets or epoch/root, and guidance hash. Run-wide/semantic resource ceilings are authorization events on the same paused run and do not create a different semantic request.

- [ ] **Step 3: Run CLI tests and confirm RED**

Run: `pytest -q tests/unit/test_cli_re_v2_protocol_25.py tests/integration/test_re_v2_protocol_25_cli.py`

Expected: parser rejects L3 and v2 resume/semantic flags.

- [ ] **Step 4: Implement lifecycle outside the monolithic CLI**

Put schema-4 preparation, exact-child scanning, guidance creation, successor selection, and run-store initialization in `protocol_25/lifecycle.py`. Keep installed-registry composition and context construction in `src/echelon/cli.py`, where `_re_v22_implementation_digest` and `_re_schema2_installed_registry` already live; pass the prepared registry/digests into lifecycle functions instead of importing `echelon.cli` back from the harness. Reuse `_re_v24_creation_lock`, `_new_re_v2_run_id`, and `_activate_re_v2_run`; do not clone provider setup.

- [ ] **Step 5: Implement mode-specific operations**

`deepen --to L3` validates clean Git and creates/reuses `new-audit-epoch`; `continue` appends only requested token/time authorization events to `paused_resource` and resumes the same run; `resume` normalizes/stores guidance and creates/reuses `audit-successor` or `closure-successor`; `--new-audit-epoch` requires explicit terminal eligibility and seeds deferred observations into the next audit context.

- [ ] **Step 6: Prove concurrent zero-duplicate creation**

Run two identical creation/resume processes under the existing no-follow `flock`; assert one schema-4 child, one manifest, one pointer update, and zero calls from the losing exact-reuse process.

- [ ] **Step 7: Run old/new CLI suites**

Run: `pytest -q tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_cli_re_v2_protocol_24.py tests/unit/test_cli_re_v2_protocol_25.py tests/integration/test_re_v2_protocol_25_cli.py`

Expected: all pass; L2 command behavior remains exact.

- [ ] **Step 8: Commit**

```bash
git add src/harness/re_v2/protocol_25/lifecycle.py \
  src/echelon/cli.py src/echelon/cli_app.py \
  tests/unit/test_cli_re_v2_protocol_25.py \
  tests/integration/test_re_v2_protocol_25_cli.py
git commit -m "feat(cli): add L3 semantic lifecycle"
```

---

### Task 14: Materialize and Report Truthful L3 State

**Files:**
- Create: `src/harness/re_v2/protocol_25/materialization.py`
- Create: `src/harness/re_v2/protocol_25/status.py`
- Create: `tests/unit/test_re_v2_protocol_25_materialization.py`
- Create: `tests/unit/test_re_v2_protocol_25_status.py`
- Modify: `src/harness/re_v2/status.py`
- Modify: `src/harness/re_v2/protocol_22/materialization.py`
- Test: `tests/unit/test_re_v2_protocol_24_status.py`
- Test: `tests/unit/test_re_v2_protocol_22_materialization.py`

**Interfaces:**
- Routes schema 4 from `render_v2_status` to `render_protocol_25_status`.
- Materializes epoch, findings, overlays, closure receipts, source roots, and explicit composed views only under `runs/<run-id>/re/l3/`.
- Produces exact banners `L3 SELECTED SCOPE COMPLETE`, `L3 PAUSED - CONTINUABLE`, `L3 BLOCKED - FROZEN FINDINGS UNRESOLVED`, and `L3 EPOCH CLOSED - NEXT AUDIT EPOCH REQUIRED`.

- [ ] **Step 1: Write failing materialization tests**

Assert exact paths from the design; sorted deterministic JSON/Markdown; raw L2 unchanged; raw L3 overlay and composed view separately inspectable; explicit refinement/supersession markers; deleted projection rebuilds byte-identically; altered projection quarantines through existing policy; no workspace `re/`; and source Git bytes/status unchanged.

- [ ] **Step 2: Write failing status/banner tests**

Assert protocol/schema/mode/lineage/selection; adopted/generated counts by layer; per-target audit/closure state; frozen/closed/unresolved/deferred counts; rounds and plateau counters; calls and usage by operation; run-wide versus semantic authorization; selected versus full coverage; retained closed receipts; exact blocker-class next action; and zero-call reuse/adoption facts.

```python
def test_deferred_observation_never_renders_complete() -> None:
    status = status_document(epoch_closed=True, deferred_count=1)
    human = render_human(status)
    assert status["state"] == "next_epoch_required"
    assert human.rstrip().endswith("L3 EPOCH CLOSED - NEXT AUDIT EPOCH REQUIRED")
    assert "L3 SELECTED SCOPE COMPLETE" not in human
```

- [ ] **Step 3: Run tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_25_materialization.py tests/unit/test_re_v2_protocol_25_status.py`

Expected: schema-4 status/materialization is unsupported.

- [ ] **Step 4: Reuse projection and status routers**

Add registered layer/kind projection hooks to the shared non-pinned materializer only if required; put L3 path/layout and composed rendering in `protocol_25/materialization.py`. Extend the one status router by exact protocol. Derive status from immutable inputs, ledger, events, graph, and budget replay; never persist a semantic status cache.

- [ ] **Step 5: Implement terminal guidance**

The complete banner states selected/full scope, zero deferred observations, workspace synthesis not run, L4 not run, and unaudited unselected domains. Plateau/incomplete banners state retained closed work, unresolved count/classes, exact `resume`/evidence/atomic-repair action, and that identical continuation is zero-call. Next-epoch state prints the explicit `deepen --new-audit-epoch` command.

- [ ] **Step 6: Run status/materialization regressions**

Run: `pytest -q tests/unit/test_re_v2_status.py tests/unit/test_re_v2_protocol_22_status.py tests/unit/test_re_v2_protocol_24_status.py tests/unit/test_re_v2_protocol_25_status.py tests/unit/test_re_v2_protocol_22_materialization.py tests/unit/test_re_v2_protocol_25_materialization.py`

Expected: all pass and old human/JSON output fixtures remain exact.

- [ ] **Step 7: Commit**

```bash
git add src/harness/re_v2/status.py \
  src/harness/re_v2/protocol_22/materialization.py \
  src/harness/re_v2/protocol_25/materialization.py \
  src/harness/re_v2/protocol_25/status.py \
  tests/unit/test_re_v2_protocol_25_materialization.py \
  tests/unit/test_re_v2_protocol_25_status.py
git commit -m "feat(re-v2): report and materialize L3 closure"
```

---

### Task 15: Compatibility Gate, Documentation, and Installed Codex Pilot

**Files:**
- Create: `tests/integration/test_re_v2_protocol_25_live.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/plans/2026-08-26-re-v2-l3-semantic-audit-closure.md`

**Interfaces:**
- Proves focused schema/identity/graph/lifecycle/recovery/provider/isolation behavior and all older protocol compatibility.
- Proves an installed clean-Git Codex-provider run uses Prosaic/shared provider execution and exercises audit, closure, exact reuse, status, telemetry, and run-local materialization.
- Records evidence without claiming workspace synthesis, L4, default-engine readiness, or atomic repair.

- [ ] **Step 1: Run focused protocol-2.5 tests**

Run:

```bash
pytest -q tests/unit/test_re_v2_protocol_25*.py \
  tests/unit/test_cli_re_v2_protocol_25.py \
  tests/integration/test_re_v2_protocol_25_controller.py \
  tests/integration/test_re_v2_protocol_25_recovery.py \
  tests/integration/test_re_v2_protocol_25_cli.py
```

Expected: all pass; live provider test remains explicitly skipped unless its opt-in environment is present.

- [ ] **Step 2: Run the complete RE v2 and provider matrix**

Run:

```bash
pytest -q tests/unit/test_re_v2*.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_cli_re_v2_protocol_24.py \
  tests/unit/test_cli_re_v2_protocol_25.py \
  tests/integration/test_re_v2*.py \
  tests/contract/test_re_v2_bounded_api.py \
  tests/unit/test_squad_provider.py
```

Expected: all pass. Record exact pass/skip counts in this plan after execution.

- [ ] **Step 3: Verify frozen authority source and canonical compatibility**

Run:

```bash
git diff bcb9a56e --exit-code -- src/harness/re_v2/protocol_24
pytest -q tests/unit/test_re_v2_protocol_compatibility.py
```

Expected: no protocol-2.4 source diff and all schema-1/2/3 fixture digests pass. Also inspect every modified protocol-2.2 file against `_re_schema2_installed_registry()` and prove no pinned implementation module changed.

- [ ] **Step 4: Run the complete repository suite**

Run: `pytest`

Expected: zero failures. Record exact pass/skip/deselect counts and separately identify any environment-only retry with the exact isolated rerun result.

- [ ] **Step 5: Install Echelon and refresh a disposable real workspace**

Run:

```bash
bash scripts/install.sh
```

In a disposable clean real workspace, run the normal `echelon workspace migrate-to-prosaic` flow. Verify installed `echelon.re-validator` and `echelon.re-resolver` bytes and frontmatter match repository sources. Confirm the workspace and every selected source report empty `git status --short` before child creation.

- [ ] **Step 6: Run the real Codex pilot**

Use `harness.llm.cli: codex`, a completed L1 or L2 parent, at least two selected domains in one source, and explicit bounded run-wide/semantic resources. The pilot must prove:

1. missing selected L2 is generated or exact selected L2 is adopted before audit;
2. one domain target passes with zero findings;
3. another domain or source target freezes at least one repairable finding;
4. one resolution overlay, target assessment, passing source guard, and closure receipt are accepted;
5. repeated identical request and repeated identical guidance add zero dispatches;
6. status JSON/human banners, events, ledger, candidates, materialization, and telemetry agree;
7. audit and closure usage are separately attributable;
8. source Git commits, bytes, and status remain unchanged; and
9. one practical crash boundary resumes without a duplicate provider call.

If the real model returns no repairable finding, use a deterministic fixture-backed loopback run for the repair branch and record that limitation honestly; do not manipulate real source or provider output to manufacture a finding.

- [ ] **Step 7: Inspect telemetry for efficiency and correctness**

Record audit target count, frozen findings by class/rule/scope, closed per round, unresolved/deferred counts, call counts by audit/resolution/recheck/guard, known versus conservatively reserved tokens, active duration, plateau outcome, successor reuse, and zero-dispatch reuse. Verify no target is audited twice within one epoch, no closed finding re-enters a later round, and telemetry contains only guidance identity—not raw guidance text.

- [ ] **Step 8: Update release/finding documentation from evidence**

Document protocol/schema, commands, fixed limits, truthful terminal meanings, test counts, pilot run IDs, provider/model/effort evidence, usage, clean-Git proof, and remaining EGR-168/EGR-169/EGR-170 boundaries. Mark only the L3 increment of EGR-169 complete when every success criterion is evidenced.

- [ ] **Step 9: Run final diff and placeholder checks**

Run:

```bash
git diff --check
rg -n 'T''BD|T''ODO|implement l''ater|fill i''n|appropriate e''rror|similar t''o|write tests f''or' \
  src/harness/re_v2/protocol_25 tests/*/test_re_v2_protocol_25* \
  prosaic/subagents/echelon.re-validator.md \
  prosaic/subagents/echelon.re-resolver.md \
  docs/superpowers/plans/2026-08-26-re-v2-l3-semantic-audit-closure.md
```

Expected: no diff errors and no placeholders.

- [ ] **Step 10: Commit evidence and documentation**

```bash
git add CHANGELOG.md docs/findings/echelon-grounded-review-register.md \
  docs/superpowers/plans/2026-08-26-re-v2-l3-semantic-audit-closure.md \
  tests/integration/test_re_v2_protocol_25_live.py
git commit -m "docs(re-v2): record L3 semantic closure evidence"
```

## Final Acceptance Checklist

- [ ] Protocol 2.5/schema 4 loads exactly; old manifest and authority bytes remain unchanged.
- [ ] L3 from L1 fills L2 first; L3 from L2 performs zero unnecessary L2 provider calls.
- [ ] Domain and source audit targets bind exact selected authority and freeze one stable epoch.
- [ ] Finding identity is insensitive to prose and sensitive to structured authority.
- [ ] All repair is expressed as L3 overlays; accepted L0/L1/L2 objects remain immutable.
- [ ] Closure cannot add epoch work, and the source guard prevents provisional target closure from becoming a false source claim.
- [ ] Deferred observations force `next_epoch_required`; zero-finding epochs close without resolver/recheck calls.
- [ ] Semantic resources are independent; fixed attempts/rounds/plateau cannot be raised.
- [ ] Two no-reduction rounds or three total rounds stop closure; closed siblings remain adoptable.
- [ ] Exact request and guidance reuse issue zero provider calls; guided repair creates immutable successors.
- [ ] Recovery is at-most-once across all 16 durable boundaries.
- [ ] L3 materialization is run-local, deterministic, and explicit about lower-layer refinement.
- [ ] Status ends with one truthful prominent banner and an exact next action.
- [ ] All model work uses Prosaic and the existing shared provider machinery across configured providers.
- [ ] Focused, compatibility, full-suite, and real Codex pilot gates pass before merge.
- [ ] Workspace synthesis, L4, default-engine cutover, and atomic lower-artifact repair remain out of scope.
