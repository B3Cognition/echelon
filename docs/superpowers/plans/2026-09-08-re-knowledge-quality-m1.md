# RE Knowledge Quality M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a new repaired-contract L4 plan from certifying missing category assessments or dispatching analyzable evidence without a relevant subject.

**Architecture:** Extend the existing content-addressed exhaustive policy with a schema-2 subtype for the stronger M1 contract. Reuse the existing planner, evidence packer, exact context sizing and input store; validate the stronger contract both before activation and when loading inputs. Existing schema-1 policies, manifests and default CLI routing remain unchanged.

**Tech Stack:** Python dataclasses, existing RE canonical objects and pytest with synthetic local Git fixtures.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`, milestone M1 and sections 5, 6, 9 and 10.

## Global Constraints

- "Repair the knowledge path incrementally; do not replace the whole engine or add another user-facing protocol selector."
- "Historical ledgers, accepted candidates and publications remain immutable."
- "Do not install or declare RE repaired after M1 alone."
- "No paid provider runs, installation, workspace migration, existing-run mutation, or budget increases are authorized by this design-writing step."
- User authorized implementation in the current checkout. Work on `codex/re-knowledge-quality-repair`; preserve all pre-existing uncommitted changes. Do not commit those changes as part of M1 without a separate request.
- Keep all source repositories, OptaSearch stashes, installed CLI defaults and running RE processes untouched. Tests use temporary synthetic inputs only.

## Scope and dependencies

This is one tightly coupled milestone with three sequential test cycles. M2 owns LLM discovery, reviewed category applicability and semantic quality/debt handling; M3 owns the simple CLI, refresh, synthesis and publication integration; M4 owns live evaluation. M1 deliberately refuses unassessed categories rather than manufacturing applicability or treating a generated evidence index as semantic completeness. The initial production preparation still generates sparse category indexes, so the repaired contract must refuse those inputs until M2 supplies reviewed discovery. Existing callers continue using the legacy policy until release routing changes in M3/M4.

### Task 1: Version and enforce the stronger preactivation contract

**Files:**
- Modify: `src/harness/re_v2/protocol_28/policies.py` — schema-2 policy subtype and opt-in internal factory, preserving schema-1 serialization/defaults.
- Modify: `src/harness/re_v2/protocol_28/planning.py` — repaired-plan structural validation and evidence/subject binding while packing.
- Modify: `src/harness/re_v2/protocol_28/preparation.py` — resolve the intent's exact policy identity and preserve relevant subjects through exact splitting.
- Modify: `src/harness/re_v2/protocol_28/inputs.py` — run repaired coverage validation on creation and durable load.
- Create: `tests/unit/test_re_v2_knowledge_quality.py` — focused behavioral regressions using real planning/preparation fixtures.
- Existing covering suites: `tests/unit/test_re_v2_protocol_28_{policies,planning,preparation,inputs,context,graph,artifacts,lifecycle}.py` and `tests/integration/test_re_v2_protocol_28_provider.py`.

**Interfaces:**
- Consume `ExhaustivePolicyV1`, `ExhaustivePlanV1`, `ExhaustiveSubjectCatalogV1`, `SnapshotEvidenceCatalogV1` and `Protocol28CreationInputs` without replacing their stores or controllers.
- Produce `ExhaustivePolicyV2(ExhaustivePolicyV1)` with schema version 2 and identical resource ceilings.
- Produce `build_repaired_exhaustive_policy(*, producer_contract_hash: str | None = None, verifier_contract_hash: str | None = None) -> ExhaustivePolicyV2`.
- Produce `validate_exhaustive_plan_coverage(plan: ExhaustivePlanV1, subjects: ExhaustiveSubjectCatalogV1, evidence: SnapshotEvidenceCatalogV1, policy: ExhaustivePolicyV1) -> None`; legacy policies retain their pinned interpretation, repaired policies reject unassessed categories and ungrounded slices with `Protocol28PlanningError`.
- Use the existing `prepare_protocol_28_request` signature; policy selection comes from the durable intent hash, never a mutable runtime boolean or new user flag.

- [x] **Cycle A / RED: reproduce lost subjects and false vacancies.**

Create tests that use `_authorities` and `_preparation_fixture` from the existing suites. First reproduce the current defects with an otherwise valid policy carrying the repaired schema identity. A full category fixture uses one evidence-backed subject assigned to all existing domain categories, plus enough distinct raw shards to force multiple bins. Primary evidence must still be assigned exactly once. For each primary shard, require an attached primary or supporting subject whose declared evidence includes that shard and whose category matches the entry. Sparse discovery and empty catalogs must not produce successful repaired plans.

```python
with pytest.raises(Protocol28PlanningError, match="unassessed"):
    build_exhaustive_plan(parent, l3, evidence, sparse_subjects, repaired_policy, selection)

for entry in target.entries:
    attached = set(entry.primary_subject_ids + entry.supporting_subject_ids)
    for shard_id in entry.primary_snapshot_evidence_ids:
        assert any(
            subject.identity in attached and shard_id in subject.evidence_ids
            and entry.category_id in subject.category_ids
            for subject in subjects.subjects
        )
```

Run `pytest -q tests/unit/test_re_v2_knowledge_quality.py`; record the missing behavior failures before changing production code. Use runtime lookup for the absent policy factory during the initial test cycle so collection itself succeeds.

- [x] **Cycle A / GREEN: implement opt-in policy and safe packing.**

Keep the default builder schema 1. Parameterize the existing policy's fixed schema check through a class variable, add its schema-2 subtype, and decode only the supported subtype on schema 2. No optional field changes historical policy JSON. The new factory uses the same limits and role hashes as the existing builder.

```python
class ExhaustivePolicyV2(ExhaustivePolicyV1):
    SCHEMA_VERSION = 2

def build_repaired_exhaustive_policy(**contracts):
    legacy = build_initial_exhaustive_policy(**contracts)
    return ExhaustivePolicyV2(**{
        field: 2 if field == "schema_version" else getattr(legacy, field)
        for field in legacy.FIELDS
    })
```

For repaired planning, retain exactly-once primary subjects/records/evidence. Select supporting subjects deterministically from the same target/category, using their explicit evidence membership; include their serialized bytes when deciding bin boundaries. Reject orphan analyzable evidence instead of assigning an unrelated fallback subject. Reject missing category work or legacy vacancy receipts: M1 has no reviewed non-applicability authority. Re-run the new tests and the existing planning/policy suites.

- [x] **Cycle B / RED: prove real preparation and exact splitting obey the gate.**

Build a synthetic source through `_preparation_fixture`, replace the intent's policy ID with the repaired factory's ID using the fixture role hashes, and call actual `prepare_protocol_28_request`. Assert sparse generated discovery raises an actionable unassessed-category error and publishes no child. Exercise the actual exact-size splitter on a complete repaired category plan with multiple shards: every split retains only valid, relevant subject bindings and stays within the frozen context/supporting-subject bounds. Keep the existing finding-closure no-split regression intact.

```python
intent = replace(intent, exhaustive_policy_catalog_id=repaired_policy.identity)
with pytest.raises(Protocol28PlanningError, match="unassessed"):
    prepare_protocol_28_request(workspace, intent, parent, options)
assert not (workspace / "runs" / options.run_id).exists()
```

- [x] **Cycle B / GREEN: integrate preparation and exact sizing.**

Resolve legacy/repaired policy candidates using their exact content hashes against the durable intent. Reject any unmatched hash as before. Use the same provider/executor contracts. After exact splitting, validate repaired bindings and limits before constructing creation inputs. Do not add a model call, generic subject, default switch or extra budget to make sparse preparation succeed. Run the new suite and the 29-test planning/preparation baseline.

- [x] **Cycle C / RED: prove an internally consistent false plan cannot bypass the gate.**

Build a valid self-contained synthetic creation fixture, change policy/plan/request/manifest hashes consistently to the repaired contract, and retain a legacy vacancy or remove an entry's subject binding. Assert input validation rejects the false plan before activation even if its hashes and a hypothetical verifier PASS are consistent. Cover persisted loading by changing canonical stored input files and manifest references, not mocking the loader. Retain an unchanged legacy round-trip and load as a compatibility control.

- [x] **Cycle C / GREEN: enforce repaired coverage on both input boundaries.**

Call the shared validator at the end of `_validate_bindings`; translate planning errors to `Protocol28InputError`. Validate exact category coverage, target-local subject/evidence references and primary/supporting bounds. A structural failure must never reach the provider or yield an accepted full root. No global requirement for a minimum claim count: empty/nonbehavioral evidence and semantic completeness belong to reviewed dispositions, not invented claims.

- [x] **Verification and focused review.**

Run the new suite and all protocol-2.8 unit/integration tests with the repository's pytest configuration. Run `git diff --check`. Review only the incremental M1 changes against the recorded dirty baseline; preserve existing uncommitted fixes. Record passing counts and any pre-existing failures explicitly. Keep all changes uncommitted for user review.

## Plan self-review

- The policy subtype, planner guard, preparation resolver and input loader share the same class and hash identity. No path selects stronger semantics from an unfrozen runtime flag.
- Subject packing precedes exact serialization sizing; both use the same frozen catalogue and preserve primary coverage. Finding-specific contexts retain the existing evidence-completeness safeguards.
- M1 covers the structural subset of R1–R4 and the M1 stop condition. It does not claim LLM applicability review, better semantic output, refresh, synthesis or consumer release readiness; those remain the already-approved M2–M4 work, not extra scope.

## Progress

- Baseline before M1: 29 planning/preparation tests passed in 39.23s.
- Branch created in the user-requested current checkout; pre-existing dirty changes preserved.
- Cycle A: observed missing-contract failures, then four behavioral failures after adding the contract; all 23 knowledge-quality/planning/policy checks passed after the packing repair.
- Cycle B: real preparation rejected the unrecognized intent and exact sizing could not split support-only evidence before the repair; all 36 knowledge-quality/planning/preparation checks passed afterward.
- Cycle C: creation accepted hash-consistent missing-category/subject plans before input-boundary validation. Additional tests reproduced five obligation-accounting gaps (primary subjects, records, ledger, target binding, category evidence); all now pass. Durable round-trip rejects a structurally false plan even after every canonical object and manifest hash is updated consistently.
- Independent review reproduced two additional boundary defects: mutually consistent target/finding omissions could bypass parent obligations, and exact splitting could produce 33 supporting subjects inside the byte ceiling. Added RED→GREEN regressions and fixed both. The reviewer confirmed both fixes and reported no remaining blockers for M1 containment.
- Final full offline regression: `pytest -q tests/unit/test_re_v2_protocol_28_*.py tests/unit/test_re_v2_knowledge_quality.py tests/integration/test_re_v2_protocol_28_*.py` — 313 passed in 72.65s. Integration providers are local test doubles, not paid model calls.
- Adjacent compatibility checks: `pytest -q tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_model.py` — 56 passed in 0.55s.
- `git diff --check` passed. All three test cycles and the focused review are complete.
- No installation, default routing changes, real-workspace execution, commits or stash operations performed. M2–M4 remain pending; M1 alone is not release-ready RE.
