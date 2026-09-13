# RE Knowledge Quality M2 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development and superpowers:test-driven-development
> to implement this plan task-by-task. Keep the current reviewed working-tree
> changes uncommitted unless the user explicitly requests a commit.

**Goal:** Turn the admitted discovery/review result into secure, authenticated
analysis authority with durable revision, reconciliation, and bounded-debt
semantics that the existing L4 controller can execute.

**Architecture:** Extend the existing protocol-2.8 input and context path rather
than adding another scheduler. Raw snapshot evidence remains local authority;
providers receive a content-addressed safe projection bound to the same raw
evidence IDs. A versioned reviewed-discovery authority maps supported subjects,
category dispositions, and inventory ownership into the existing exhaustive plan.
Post-slice target and source reconciliation uses the same controller, aggregate
account, review separation, and immutable revision machinery.

**Tech Stack:** Python dataclasses and canonical JSON, existing RE v2 object/event
stores and controllers, neutral Prosaic roles, pytest with synthetic Git fixtures.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`

## Global Constraints

- Work in the current `codex/re-knowledge-quality-repair` checkout and preserve
  the existing reviewed uncommitted increment. Do not touch or stage `runs/`.
- Do not install, invoke a live/paid provider, migrate a workspace, alter source
  repositories or stashes, raise resource ceilings, merge, push, or publish.
- Retain the existing provider abstraction, neutral roles, immutable snapshots,
  controller-owned writes, bounded attempts, one aggregate account, and atomic
  activation/publication ordering.
- Raw secrets and raw provider diagnostics never enter provider input, ordinary
  logs, status, publication, or consumer snapshots. Tests use synthetic canaries.
- Preserve historical protocol readers and content identities. New semantics use
  explicit new schema/contract identities; no runtime flag reinterprets an old run.
- No second scheduler, provider framework, parser platform, recursive repair loop,
  or policy-selection menu.
- Every production behavior starts with a focused failing test, observed failing
  for the missing behavior, followed by the minimum implementation and regression
  verification.

---

### Task 1: Safe provider projection for protocol-2.8 analysis

**Files:**
- Create: `src/harness/re_v2/protocol_28/safe_evidence.py`
- Modify: `src/harness/re_v2/knowledge_evidence.py`
- Modify: `src/harness/re_v2/protocol_28/model.py`
- Modify: `src/harness/re_v2/protocol_28/inputs.py`
- Modify: `src/harness/re_v2/protocol_28/preparation.py`
- Modify: `src/harness/re_v2/protocol_28/context.py`
- Test: `tests/unit/test_re_v2_protocol_28_safe_evidence.py`
- Test: `tests/unit/test_re_v2_protocol_28_context.py`
- Test: `tests/unit/test_re_v2_protocol_28_inputs.py`

**Interfaces:**

- Produces `SafeSnapshotEvidenceObjectV1`, which binds one existing raw
  `SnapshotEvidenceShardV1`/empty/non-text identity to a provider-safe canonical
  object and the exact `security_policy_id()`.
- Produces `SafeSnapshotEvidenceCatalogV1` with the raw
  `SnapshotEvidenceCatalogV1.identity`, security policy identity, and exactly one
  safe row for every evidence object that may enter a slice context.
- Produces a new protocol-2.8 creation-input and manifest subtype that explicitly
  binds the safe catalogue ID. Existing manifest/input subtypes remain byte-for-byte
  readable and keep their historical raw-context behavior only for historical runs.
- `build_protocol_28_slice_context()` selects safe objects for the new subtype;
  raw evidence objects remain available to deterministic anchor validation but are
  never serialized into the provider payload.

- [x] **Step 1: Write failing safe-projection tests.**

  Use a real synthetic snapshot containing ordinary source, a credential
  assignment, a private-key-shaped file, a malicious instruction comment, empty
  data, and non-UTF-8 input. Stage the real protocol-2.8 evidence catalogue, build
  the new safe catalogue, and assert:

  ```python
  assert safe.raw_catalog_id == raw.identity
  assert safe.security_policy_id == security_policy_id()
  assert set(safe.raw_evidence_ids) == {
      item.identity for item in (*raw.shards, *raw.empty_receipts, *raw.nontext_dispositions)
  }
  assert CANARY not in safe.provider_bytes()
  ```

  Mutation caught: serializing raw shards, omitting a raw evidence member, or
  changing the policy without changing the catalogue identity.

- [x] **Step 2: Run the focused tests and observe RED.**

  Run:

  ```bash
  pytest -q tests/unit/test_re_v2_protocol_28_safe_evidence.py
  ```

  Expected: collection/import or behavioral failures because the safe catalogue
  and builder do not exist.

- [x] **Step 3: Implement the safe evidence catalogue.**

  Reuse the scanner and exclusion semantics from `knowledge_evidence.py` through
  a new pure `screen_source_bytes(raw: bytes) -> ScreenedSourceBytesV1` helper.
  Preserve byte offsets and
  raw evidence IDs while replacing secret spans with equal-length masking. For
  excluded/private-key/non-text evidence, emit metadata-only dispositions. Store
  the raw-to-safe mapping locally and validate exact one-to-one closure. Do not
  copy raw bytes into the safe object.

- [x] **Step 4: Write failing context and durable-input tests.**

  Build and persist the new input subtype, then call the real slice renderer.
  Assert permitted anchors retain raw evidence identities and offsets, provider
  `snapshot_evidence` contains only safe objects, and no canary is present in the
  complete producer or verifier context. Tamper with one safe row, policy ID,
  raw catalogue binding, manifest reference, or authority object and assert input
  load fails before activation. Load an unchanged historical fixture successfully.

- [x] **Step 5: Run the new context/input tests and observe RED.**

  Run:

  ```bash
  pytest -q tests/unit/test_re_v2_protocol_28_safe_evidence.py \
    tests/unit/test_re_v2_protocol_28_context.py \
    tests/unit/test_re_v2_protocol_28_inputs.py
  ```

  Expected: new-subtype/context assertions fail while historical controls pass.

- [x] **Step 6: Bind the safe catalogue into new immutable inputs.**

  Add the smallest versioned manifest/request/input subtype needed to authenticate
  the safe catalogue. Update preparation to create it before plan activation and
  include every safe object in required authority closure. Update loaders and
  context rendering by subtype; never infer new semantics from a policy ID alone.
  Enforce the context bound after safe serialization.

- [x] **Step 7: Verify Task 1.**

  Run the focused tests above, all protocol-2.8 evidence/context/input/preparation
  tests, all knowledge-evidence tests, and `git diff --check`. Record exact RED and
  GREEN evidence, changed files, and any historical compatibility limitation.

### Task 2: Versioned category-aware discovery and independent review

**Files:**
- Modify: `src/harness/re_v2/knowledge_discovery.py`
- Modify: `src/harness/re_v2/knowledge_discovery_review.py`
- Modify: `src/harness/re_v2/knowledge_dispatch.py`
- Modify: `src/harness/re_v2/knowledge_review_dispatch.py`
- Modify: `prosaic/subagents/echelon.re-discoverer.md`
- Modify: `prosaic/subagents/echelon.re-discovery-reviewer.md`
- Modify: `runtime/workflow/phases/re-knowledge-discovery.md`
- Modify: `runtime/workflow/phases/re-knowledge-discovery-review.md`
- Test: `tests/unit/test_re_v2_knowledge_discovery_v2.py`
- Test: `tests/unit/test_re_v2_knowledge_discovery_review_v2.py`

**Interfaces:**

- Discovery response schema 2 adds `category_ids` to each subject and replaces
  bare obligation pairs with exactly one row per required target/category:

  ```python
  {
      "target": str,
      "category": str,
      "disposition": "analyze" | "not-applicable" |
                     "unknown" | "outside-requested-depth",
      "subject_keys": list[str],
      "rationale": str,
      "evidence_ids": list[str],
  }
  ```

- Review response schema 2 contains the existing domain, subject, inventory and
  overlap review plus an `obligations` row for each candidate obligation. Review
  cannot edit candidate subject membership or disposition.
- Schema-1 proposal/review receipts remain readable and retain their old identities,
  but are not activation authority under the new contract.
- Deep proposals forbid `outside-requested-depth`; `analyze` requires at least one
  target-local supported subject carrying the category; `not-applicable` requires
  visible scoped evidence and independent support; `unknown` is explicit and never
  converted to absence. A ready review may contain eligible bounded unknowns but
  records them for Task 4; incomplete ownership, unsupported subject/category, or
  unattempted work requires revision.

- [x] **Step 1: Write failing schema-2 discovery tests.**

  Cover application, deployment-only, empty, and partial-evidence sources. Assert
  exact category coverage, target-local subject membership, depth restrictions,
  evidence support, stable normalized identities under row reordering, and schema-1
  replay compatibility. Reject fabricated categories, cross-target subject keys,
  unsupported not-applicable, deep outside-depth, and implicit missing rows.

- [x] **Step 2: Run discovery tests and observe RED.**

  ```bash
  pytest -q tests/unit/test_re_v2_knowledge_discovery_v2.py
  ```

- [x] **Step 3: Implement schema-2 discovery admission.**

  Decode by exact schema version. Preserve schema-1 normalization and receipt
  construction unchanged. Give schema-2 proposal, normalized object, response, and
  receipt distinct identities. Keep model text passive: no filesystem/state writes
  outside the existing controller-owned object store and no plan activation.

- [x] **Step 4: Write failing schema-2 review tests.**

  The reviewer receives normalized candidate plus authenticated safe context, not
  producer reasoning. Assert exact obligation coverage; a false-ready review with
  unsupported not-applicable, altered subject membership, missing evidence, or
  unresolved ownership is rejected. Assert separately invoked review and schema-1
  replay remain unchanged.

- [x] **Step 5: Run review tests and observe RED.**

  ```bash
  pytest -q tests/unit/test_re_v2_knowledge_discovery_review_v2.py
  ```

- [x] **Step 6: Implement schema-2 independent review admission and roles.**

  Extend the neutral roles with paired ALWAYS/NEVER rules and exact schema-2
  authorial contracts. Keep phase files as dispatcher/context/output contracts.
  Preserve one shared account, separate invocation, screening, capture, and replay.
  A review receipt records normalized category rows and exact candidate/context
  roots but still states `analysis_certified: false`.

- [x] **Step 7: Verify Task 2.**

  Run both new files, every `test_re_v2_knowledge_discovery*`, dispatch/review tests,
  role/catalog/packaging tests, and `git diff --check`.

### Task 3: Activate reviewed discovery as protocol-2.8 planning authority

**Files:**
- Create: `src/harness/re_v2/knowledge_activation.py`
- Modify: `src/harness/re_v2/protocol_28/planning.py`
- Modify: `src/harness/re_v2/protocol_28/inputs.py`
- Modify: `src/harness/re_v2/protocol_28/preparation.py`
- Modify: `src/harness/re_v2/protocol_28/context.py`
- Test: `tests/unit/test_re_v2_knowledge_activation.py`
- Test: `tests/integration/test_re_v2_knowledge_activation.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ReviewedDiscoveryAuthorityV1:
    schema_version: int
    snapshot_id: str
    partition_id: str
    security_policy_id: str
    source_id: str
    depth: str
    active_revision_id: str
    proposal_receipt_id: str
    review_receipt_id: str
    subject_catalog_id: str
    category_assessment_ids: tuple[str, ...]
    inventory_assessment_ids: tuple[str, ...]

def activate_reviewed_discovery(
    acquisition: DiscoveryAcquisition,
    account: KnowledgeDispatchAccount,
    review: DiscoveryReviewController,
    l3_targets: L3TargetProjectionCatalogV1,
    evidence: SnapshotEvidenceCatalogV1,
) -> ReviewedDiscoveryAuthorityV1: ...
```

- The function runs under the existing RE lock and only reads a ledger-committed
  `review_ready` result for the active acquisition revision.
- It maps reviewed safe projection ranges to authenticated overlapping raw L4
  evidence IDs without exposing raw bytes. Every analyzable raw evidence member is
  owned exactly once or has a reviewed non-behavioral/excluded disposition.
- Discovered domains reconcile to selected L3 domain targets through a versioned,
  evidence-supported target mapping. Ambiguous/unmapped/duplicate targets block;
  directory/name equality alone is insufficient. The source target maps exactly.
- `analyze` rows generate `ExhaustiveSubjectV1` category memberships.
  `not-applicable` and allowed `outside-requested-depth` rows generate authenticated
  `ReviewedCategoryDispositionV1` objects. The repaired plan may omit a slice only
  when its vacancy receipt points to one of those exact objects. Unknown rows do
  not disappear and are carried to Task 4.
- The new protocol-2.8 input subtype binds every selected source's reviewed
  authority and rejects mechanical `_build_evidence_subjects` as activation input.

- [x] **Step 1: Write failing unit tests for exact activation.**

  Start from real snapshot, discovery, acquisition, dispatch and independent review
  receipts. Assert deterministic subject/category/evidence identities, exact raw
  evidence ownership, supported not-applicable handling, and active-revision
  binding. Mutate review receipt, target mapping, range, security policy, category,
  source, or revision and assert no activation object is written.

- [x] **Step 2: Run unit tests and observe RED.**

  ```bash
  pytest -q tests/unit/test_re_v2_knowledge_activation.py
  ```

- [x] **Step 3: Implement activation and category disposition authority.**

  Reconstruct proposal/review using their boundaries, authenticate the account and
  active acquisition revision, map only within the selected source, and write all
  child objects before the authority root. Reopening reads and recomputes the same
  root without writes. Never infer support from names or content-addressed object
  presence alone.

- [x] **Step 4: Write failing real-preparation integration tests.**

  Replace the mechanical subject builder with reviewed authority in the new input
  subtype. A reviewed deployment-only source creates source-level useful work plus
  authenticated domain/category non-applicability, while an application source
  creates grounded domain/source slices. A schema-1/passive review, unknown deep
  obligation, orphan evidence, or mismatched target blocks before child creation.

- [x] **Step 5: Run integration tests and observe RED.**

  ```bash
  pytest -q tests/integration/test_re_v2_knowledge_activation.py
  ```

- [x] **Step 6: Integrate reviewed authority into planning and inputs.**

  Extend `build_exhaustive_plan` and repaired validation with explicit reviewed
  inputs; historical call signatures/default behavior remain unchanged. Bind the
  reviewed authority and safe evidence catalogue in request/manifest/required
  object closure. Contexts carry normalized subject/category obligations and their
  limits, never discovery transcripts or private mappings.

- [x] **Step 7: Verify Task 3.**

  Run new activation tests, all knowledge discovery/account/dispatch tests, all
  protocol-2.8 planning/preparation/input/context tests, and `git diff --check`.

### Task 4: Durable post-activation revision, reconciliation, and bounded debt

**Files:**
- Create: `src/harness/re_v2/knowledge_revision.py`
- Create: `src/harness/re_v2/protocol_28/reconciliation.py`
- Create: `src/harness/re_v2/protocol_28/debt.py`
- Modify: `src/harness/re_v2/protocol_28/controller.py`
- Modify: `src/harness/re_v2/protocol_28/events.py`
- Modify: `src/harness/re_v2/protocol_28/ledger.py`
- Modify: `src/harness/re_v2/protocol_28/lifecycle.py`
- Modify: `src/harness/re_v2/protocol_28/model.py`
- Modify: `src/harness/re_v2/protocol_28/status.py`
- Create: `prosaic/subagents/echelon.re-knowledge-reconciler.md`
- Create: `runtime/workflow/phases/re-knowledge-reconciliation.md`
- Modify: `runtime/workflow/definition.yaml`
- Modify: `docs/agent-role-catalog.md`
- Test: `tests/unit/test_re_v2_knowledge_revision.py`
- Test: `tests/unit/test_re_v2_protocol_28_reconciliation.py`
- Test: `tests/unit/test_re_v2_protocol_28_debt.py`
- Test: `tests/integration/test_re_v2_knowledge_revision_recovery.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class KnowledgeRevisionReceiptV1:
    schema_version: int
    logical_run_id: str
    previous_revision_id: str
    revision_id: str
    cause_id: str
    affected_obligation_ids: tuple[str, ...]
    reusable_result_ids: tuple[str, ...]
    invalidated_result_ids: tuple[str, ...]
    compatibility_receipt_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ReviewedKnowledgeDebtAcceptanceV1:
    schema_version: int
    logical_run_id: str
    snapshot_id: str
    obligation_ids: tuple[str, ...]
    debt_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    authorization_id: str
```

- One committed revision manifest points to context, plan, subject catalogue,
  dependency map, invalidation receipt, aggregate account, and inherited counters.
  The active pointer advances last. Incomplete staging is never active.
- Evidence expansion after activation consumes the same two-round counter and same
  aggregate account. Splits/merges retain origin IDs and counters.
- Reconciliation runs after all slices of a target, then after all targets of a
  source. It checks category coverage, contradictions, call chains, evidence
  support, and inherited debt; a slice PASS is insufficient.
- Eligible reviewed ambiguity may become `accepted_with_debt` under the frozen new
  simple-workflow authorization. Missing work, unsupported claims, structural or
  security failure, unassessed categories, provider/resource failure, or unfinished
  reconciliation remain blocked.
- Run roots authenticate ordinary and debt-backed acceptances. Status exposes
  running, complete, complete-with-limitations, or needs-attention without calling
  incomplete active work terminally blocked.

- [x] **Step 1: Write failing revision/recovery tests.**

  Inject faults after request intent, each staged object, invalidation receipt,
  revision manifest, and active-pointer replacement. Reopen and assert only a fully
  committed revision becomes active; resolved acquisition and settled reservations
  are reused; affected results and transitive source roots are invalidated; proven
  independent siblings require explicit compatibility receipts.

- [x] **Step 2: Run revision tests and observe RED.**

  ```bash
  pytest -q tests/unit/test_re_v2_knowledge_revision.py \
    tests/integration/test_re_v2_knowledge_revision_recovery.py
  ```

- [x] **Step 3: Implement revision receipts on existing run storage.**

  Use the existing run/object/event stores and owner lock. Stage immutable children
  and publish the revision manifest/pointer last. Recompute closure on replay; do
  not repair missing authority during a read. Preserve aggregate resource and
  attempt identities across every revision.

- [x] **Step 4: Write failing reconciliation/debt tests.**

  Cover a missed call chain split across slices, contradictory target claims,
  unsupported absence, unavailable dynamic dependency, exhausted provider budget,
  incomplete category, and accepted inherited debt. Assert only the investigated
  dynamic dependency is eligible debt and that exact debt remains in target/source
  roots. Repeated unchanged outcomes terminate without another invocation.

- [x] **Step 5: Run reconciliation/debt tests and observe RED.**

  ```bash
  pytest -q tests/unit/test_re_v2_protocol_28_reconciliation.py \
    tests/unit/test_re_v2_protocol_28_debt.py
  ```

- [x] **Step 6: Implement bounded reconciliation and debt authority.**

  Reuse the existing producer/verifier execution and reservation machinery with
  explicit reconciliation work items, not a nested controller. Persist reviewer
  feedback before the next permitted attempt. Build target/source roots only after
  deterministic validation and independent review. Record debt authorization and
  exact lineage; never treat uncertainty as completion by default for historical
  runs.

- [x] **Step 7: Verify Task 4 and M2.**

  Run all new tests, every `tests/unit/test_re_v2_knowledge*.py`, every protocol-2.8
  unit/integration test, `tests/unit/test_re_v2_protocol_28_roles.py`,
  `tests/unit/test_role_contracts.py`, `tests/kernel/test_workflow_validator.py`,
  `tests/kernel/test_agent_role_catalog_docs.py`,
  `tests/unit/test_prosaic_package_install.py`, and `git diff --check`.
  Confirm no test invokes a native provider or writes outside its temporary fixture.
  Update the design status accurately: M2 complete only if all four tasks and an
  independent whole-increment review pass. Do not claim synthesis, refresh, CLI, or
  release readiness; those are M3/M4.

## Plan self-review

- Task 1 provides the safe provider evidence that Tasks 2–4 reference; raw evidence
  remains local authority and existing anchors keep stable identities.
- Task 2 produces category-aware candidate/review authority; Task 3 is the only
  activation bridge and refuses older passive receipts.
- Task 3 produces the exact subject/category/dependency authority Task 4 revises
  and reconciles. Task 4 owns no new scheduler or budget.
- Historical input/proposal/review readers remain explicit schema branches. No old
  content identity changes because new fields live only in new subtypes.
- M3 synthesis/publication, source-refresh orchestration, two-action CLI, and the
  complete offline lifecycle intentionally follow this plan rather than being
  partially enabled here.
