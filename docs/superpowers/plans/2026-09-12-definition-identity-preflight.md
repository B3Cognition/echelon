# Requirement and task identity preflight implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the reviewed read-only candidate checks to FR/NFR/AC requirements, canonical tasks and authoritative Lexicon definitions without duplicating discovery validation or confusing rendered wording with immutable registry subjects.

**Architecture:** Introduce a general public wrapper using the same connection-owned checker with fixed internal role/kind policies; retain the narrower discovery wrapper and its current API. Extend exact-span scoping to validated nested declarations, preserving every unscoped descendant and ancestor. No publication, evidence reassessment or schema change occurs here. Issue occurrences, derived projections, JSON inventories and reference intervals remain explicit unsupported cases in this checkpoint.

**Tech Stack:** Existing Python artifact adapters, SQLite identity store, lifecycle planner and binding reader; pytest; no dependency.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Preserve exact labels, immutable registry subjects, existing lifecycle history, reservations, lineage and original reference receipts.
- Typed artifact captions describe rendered source, not registry subject authority. Same-identity revisions use the existing lifecycle subject/CAS checks and still require later semantic review before publication.
- Helpers use the caller-owned read transaction, never a nested public store transaction, allocation or write.
- Detected damaged authority propagates IdentityStoreError rather than becoming a provider-repair diagnostic.
- Unsupported candidate roles and interval references remain blocking diagnostics; no silent all-family coverage claim.
- No canonical publication, graph/memory writes, provider routing, or live activation in this task.

---

### Task 1: general definition policy and nested exact-span scope

**Files:** Extend `src/harness/element_identity_candidate.py`, `src/harness/element_identity_candidate_store.py` and the thin wrapper in `src/harness/element_identity_store.py`. Create `tests/unit/test_definition_identity_candidate.py`; extend `docs/element-identity-candidates.md`. Preserve the reviewed discovery tests. No parser grammar, schema or storage-persistence changes; report a necessary change to the controller before making it.

**Dependencies:** Consume the final reviewed discovery checker, not the first unreviewed commit. Inspect its current helper/request signatures before modifying them. Reuse its authority prevalidation, same-transaction lifecycle planning, current/projected content comparison, preserved-reference states and exact source-claim matching. The task's change is the role policy and span scoping, not a second checker.

**New public types/API:**

```python
@dataclass(frozen=True, slots=True)
class IdentityEditScope:
    writable_paths: tuple[str, ...]
    element_ids: tuple[str, ...]
    unowned_text_paths: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class IdentityCandidateCheck:
    diagnostics: tuple[CandidateDiagnostic, ...]
    references: tuple[CandidateReferenceState, ...]

IdentityStore.check_identity_candidate(
    *, spec_id: str,
    artifacts: Sequence[CandidateArtifact],
    scope: IdentityEditScope,
    changes: Sequence[lifecycle.LifecycleChange] = (),
) -> IdentityCandidateCheck
```

Preserve `DiscoveryEditScope`, `DiscoveryCandidateCheck` and `check_discovery_candidate` exactly. Normalize the two strict public scope types through one shared validation function parameterized only by the wrapper's fixed internal policy. Do not expose a caller-supplied policy override. The shared checker may take an internal result factory so each wrapper returns its promised exact result type without duplicating the algorithm.

General supported roles: all reviewed discovery roles plus `requirements`, `tasks` and `lexicon`. General scoped/lifecycle kinds: U, A, FR, NFR, AC, T. Definitions must still come only from the role's typed adapter; native `lexicon` is authoritative while `lexicon_projection` remains unsupported. `issues`, `lexicon_projection` and any unrecognized role remain `unsupported_role`. ISS may be an existing reference target, never a definition or lifecycle effect in this checkpoint. Discovery wrapper retains U/A-only scope/lifecycle and its original role whitelist. No generic invocation can make duplicate authoritative definitions legal by naming one a second source.

For FR/NFR/AC/T definitions, do not require `declaration.caption == head.subject`. The proposed lifecycle request preserves the immutable subject; rendered requirement wording or task title may change only with a matching explicit scoped revision and exact content. Such structural validity does not establish semantic continuity. U/A ordinary heading preservation follows the final reviewed discovery contract; the generic wrapper must not weaken it. Missing definitions, introduction/reservations, retirement/transition, aliases, damaged authority and exact baseline checks retain the shared rules.

Nested declarations in requirements are valid only when their intervals are disjoint or strictly nested. Validate containment using source offsets, rejecting crossing, identical or malformed overlapping intervals. Pure scoping must compare each definition's old/new full content and require scope for every changed declaration, including ancestors whose retained full block changes with a nested AC. This intentionally requires explicit ancestor revision/scope when that ancestor's stored content includes the edited child; it does not silently update a parent's revision or assessment.

For exact unowned-text comparison, mask only the outermost authorized declaration spans in each image, using the existing collision-free markers. Skip contained authorized spans already covered by an authorized outer span. Independently enforce exact content for unscoped descendants, so authorizing a parent does not grant permission to rewrite all its children. Authorizing a child does not implicitly authorize a changed parent. Retain discovery's overlap rejection for its supported non-nested declarations rather than broadening its grammar.

Task `requires`/`depends` and native Lexicon dependency relations are now reachable through their real adapters. Resolve exact same-spec target identities and report `inactive_dependency` whenever such a target is not active, including unassessed imported targets, retired targets and superseded targets. Proposed active creation/revision targets in the same batch may resolve. Keep interval references explicitly unsupported; do not silently treat endpoints as the full dependency set. This task does not replace existing task/Lexicon semantic or quality validators.

- [ ] Write a real-storage requirement revision test before implementation. Use an immutable subject deliberately different from the rendered requirement caption, and retain a full logical prestate snapshot:

```python
def test_requirement_revision_does_not_replace_immutable_subject(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="001-game", kind="FR", operation_id="reserve", count=1)
    before = f"- **{label}**: The player MUST move using WASD.\n"
    after = f"- **{label}**: The player MUST move using arrow keys.\n"
    old, = parse_identity_artifact(path="spec.md", role="requirements", text=before).declarations
    new, = parse_identity_artifact(path="spec.md", role="requirements", text=after).declarations
    store.apply_lifecycle(spec_id="001-game", operation_id="create", changes=(
        ElementCreate(label, "Player movement", old.content, "reserve"),))
    result = store.check_identity_candidate(
        spec_id="001-game", artifacts=(CandidateArtifact("spec.md", "requirements", before, after),),
        scope=IdentityEditScope(("spec.md",), (label,)),
        changes=(ElementRevision(label, "1", "Player movement", new.content),))
    assert result.diagnostics == ()
    assert store.lookup(spec_id="001-game", element_id=label)["revision"] == "1"
    assert store.lookup(spec_id="001-game", element_id=label)["subject"] == "Player movement"
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_definition_identity_candidate.py -q` and retain behavioral RED. Add full logical-dump equality to the test before implementation, not only the two targeted assertions shown.
- [ ] Add real adapter/storage tests before corresponding behavior for mixed FR/NFR/AC/T and legacy labels, reserved creation, exact scoped revisions, unauthorized wording/title edits, retirement/replace/split/merge, duplicate definitions across Markdown/native Lexicon, unsupported occurrence/projection roles and preserved discovery restrictions.
- [ ] Add nested FR/AC tests: legitimate explicit parent+child revisions pass structurally; child-only scope does not silently revise the parent; parent-only scope cannot alter an unscoped child; unchanged child content under a changed parent remains exact; crossing/identical source spans reject in the pure scope helper. Use real parsed nesting for supported cases and constructed typed spans only for impossible crossing input.
- [ ] Add canonical task rows with actual `req` and `depends` relations and native Lexicon DEPENDS clauses. Active exact targets resolve; imported/retired/superseded dependencies block; same-batch reserved targets may resolve; missing targets and interval references remain blocking. Preserve old evidence revision claims after proposed target edits without inserting reassessments.
- [ ] Implement fixed internal policies and shared wrapper validation, then nested exact-span masking and reachable inactive-dependency checks. Preserve the original read-only and integrity-error boundary and test one real query-only transaction per public wrapper.
- [ ] Run new definition tests plus `tests/unit/test_discovery_identity_candidate.py`, `tests/unit/test_element_artifacts.py`, `tests/unit/test_element_artifact_lexicon.py`, `tests/unit/test_element_identity_preview.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_tasks_canonical_contract.py` and `tests/unit/test_lexicon_parser.py`.
- [ ] Document the exact general/narrow role matrices, ancestor scope/revision implication and remaining unsupported formats. Self-review, run `git diff --check`, commit only task files and retain exact RED/GREEN commands/output and remaining publication/semantic gaps in the ignored report.

## Following work

This adds six-family definition preflight only. Interval/qualified references, issue occurrence authorization, derived Lexicon/source binding, JSON source-inventory checks, history tools, durable publication/CAS and graph/memory projection, managed producers, bounded repair, combined simulation and explicit rollout are still required. Do not call either read-only checker a publication gate until the existing publishers actually bind and enforce it.
