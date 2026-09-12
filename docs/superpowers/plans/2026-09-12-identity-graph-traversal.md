# Identity graph traversal implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Keep bare entity-ID lookup stable after history nodes are added and make the existing typed impact traversal include retained revision/evidence/occurrence relationships.

**Architecture:** Extend the current selector's precedence without changing qualified graph keys or arbitrary-property fallback, and extend the existing closed typed impact map. All work remains read-only on supplied graph models; source-current authorization, live managed builder/audit loading and publication integration are separate gates.

**Tech Stack:** Existing `GraphReadModel` indexes, deterministic graph query/traversal helpers, real identity history/projector fixtures, focused Python tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing graph keys remain valid.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- No live managed graph builder/audit loading, publication, source freshness certification, memory/controller/provider/producer activation or database schema changes in this task.

---

### Task 1: prefer durable entity selectors and traverse typed history

**Files:** Modify `src/echelon/graph_read.py` only for selector precedence, `src/echelon/graph_traversal.py` only for the typed impact/alias tables and small shared table-construction helpers if warranted, and `docs/element-identity-storage.md`. Create `tests/unit/test_identity_graph_traversal.py`. Preserve all existing tests and graph data model signatures; do not add a parallel traversal engine, graph builder or current-evidence verdict API.

**Interfaces remain unchanged:** `resolve_node_id(model, selector)`, `query_graph`, `impact`, `explain_node`, `neighbors`, `shortest_path`, existing `GraphReadModel`, and read-only graph indexing. Use actual `project_identity_history` output from the immediately preceding reviewed phase in integration fixtures.

**Selector contract:**

1. Preserve exact full-node-ID lookup as the first choice, and all existing input validation/whitespace/casefold behavior.
2. For non-exact shorthand, collect primary entity matches by node type and its dedicated string label property: Requirement/requirement_id, Task/task_id, Unknown/element_id, Assumption/element_id, Issue/element_id. Match the actual complete string case-insensitively; never truncate, strip numeric zeroes, coerce numbers or infer labels from revision/claim/occurrence properties. A single primary entity wins even when history nodes or unrelated arbitrary *_id properties mention that label.
3. Two or more primary entities remain ambiguous, including the same label in different qualified specs or namespaces. Use the existing bounded/sorted ambiguity formatter. Never pick a current, first, active or managed spec implicitly; a retired entity is still a durable entity.
4. With no primary match, preserve the existing suffix/arbitrary *_id fallback exactly, including unknown/ambiguous behavior and non-entity `publication_id` selectors. Explicit complete history node keys still resolve by step 1; this is not a way to guess which report/occurrence a bare repeated display ID means.

Keep the implementation at the existing selector. A small static type->label-property map is appropriate; do not build a mutable global cache, mutate node properties or introduce a second ID namespace. Do not change graph load/audit status handling or claim that successful shorthand resolution proves source freshness.

**Typed default impact policy:** Extend existing `IMPACT_RELATIONS`; preserve every old entry and the existing deterministic BFS/depth/cycle/truncation behavior. In the table below, `Entity` expands independently to Requirement, Task, Unknown, Assumption, Issue. `both` means add the exact forward and inverse typed adjacency entries, not arbitrary relation traversal:

| Stored edge | Default impact directions |
| --- | --- |
| Spec --HAS_IDENTITY--> Entity | Spec out to Entity only; no reverse through Spec membership |
| Entity --HAS_REVISION--> ElementRevision | both |
| Entity --CURRENT_REVISION--> ElementRevision | both |
| ElementRevision --SUCCESSOR_REVISION--> ElementRevision | predecessor out to successor only |
| ReferenceClaim --REFERENCES_IDENTITY--> Entity | both |
| ReferenceClaim --ASSESSES_REVISION--> ElementRevision | both |
| ReferenceClaim --HAS_SOURCE--> IdentitySource | both |
| IssueOccurrence --OCCURRENCE_OF--> Issue | both |
| IssueOccurrence --OBSERVES_REVISION--> ElementRevision | both |
| IssueOccurrence --HAS_REPORT--> IdentityReport | both |

These directions intentionally expose the potentially affected entity/history/evidence neighborhood, including older and unassessed records. This is conservative read-only impact, not an instruction to invalidate all visited stages or proof that historical evidence verifies a current revision. Preserve each returned node's exact lifecycle/revision/current-match and assessment metadata. Do not suppress terminal entities, retarget historical edges to CURRENT_REVISION, promote `identity_assessment: unassessed`, or change original complete/fingerprint/source bindings. Controller invalidation must still compare actual bound inputs later. No reverse Spec membership means an entity does not fan out to every unrelated entity solely through its common Spec; no reverse lineage means successor impact does not automatically reopen predecessors. Generic neighbors/shortest-path/all_relations retain their existing explicit semantics.

Add exact aliases to existing NODE_TYPE_ALIASES: unknown/unknowns -> Unknown; assumption/assumptions -> Assumption; issue/issues -> Issue; revision/revisions -> ElementRevision; referenceclaim/referenceclaims -> ReferenceClaim; issueoccurrence/issueoccurrences -> IssueOccurrence; identitysource/identitysources -> IdentitySource; identityreport/identityreports -> IdentityReport. Keep source/sources mapped to SourceRoot, and every other old alias unchanged. Aliases also participate in existing natural-language type inference; do not alter the inference/ranking algorithm or add broad unrelated synonym heuristics.

**First regression before production edits:** Create a real initialized authority, reserve/create/revise an FR and record an older-revision ReferenceClaim, capture and project it onto a fresh Spec/Requirement base graph. Build a GraphReadModel using the existing `_indexes` of the projected `to_dict()` document, with an explicitly unavailable audit report (this isolated fixture is not a live canonical-source audit). Before the selector fix, the bare FR label must fail as ambiguous because ElementRevision and ReferenceClaim rows repeat it; then it must resolve to the unchanged qualified Requirement key.

```python
def test_bare_entity_id_does_not_become_ambiguous_with_history(tmp_path):
    model, label, entity_key = projected_history_model(tmp_path)
    from echelon.graph_read import resolve_node_id, graph_read_exit_code
    assert resolve_node_id(model, label) == entity_key
    assert resolve_node_id(model, label.lower()) == entity_key
    assert graph_read_exit_code(model) == 1  # no fabricated current-source audit
```

The local fixture uses `IdentityStore.initialize`, `reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)`, create Scene/Original body under create, ReferenceClaim(evidence.md, a*64, span:0:9, label, "1", evidence) under evidence, and revise to Revised body under revise. Base Spec node is spec:demo and Requirement node is req:demo:<label> with requirement_id label. Project using the real `identity_history` snapshot. The unavailable report uses `SpecGraphAuditReport` with status unavailable and one graph_source_unavailable finding explaining this is a supplied-model fixture. No mocking of the projector, store, indexer or selector in this required regression.

- [ ] Add the real marked regression, run it with the checkout virtualenv and retain the actual ambiguous-selector RED after successful capture/projection. Implement the minimal selector change and verify GREEN.
- [ ] Test primary selection for all seven ID families, terminal/unassessed entities, exact legacy FR-001/composites and 999999/1000000/5,000-digit string labels. Test exact revision/claim/occurrence keys, arbitrary publication_id fallback, no-primary ambiguity, cross-spec primary ambiguity including projected/unprojected entity candidates, capped candidate formatting, and no numeric padding normalization.
- [ ] Add independent literal expected adjacency tests covering every row/type/direction expansion above, not tests that derive their expected answer from IMPACT_RELATIONS. Assert exact returned node IDs/edge triples, wrong-neighbor-type exclusions and deliberate reverse Spec/lineage exclusions. Do not set all_relations=True to make default typed tests pass.
- [ ] Use real projected replace/split/merge, retired revisions, null and old evidence, and issue occurrence history to exercise default impact from both an entity and retained source/report. Verify preserved original bindings/properties, cycle safety, deterministic order, max-depth truncation, and that unrelated entities sharing only Spec membership are excluded. Preserve existing generic all_relations/neighbors/shortest_path behavior.
- [ ] Test each new alias through actual query_graph with explicit node_type and representative natural-language queries; old aliases including source/sources remain unchanged. Verify all operations leave the model/document/metadata/audit unchanged, perform no storage/filesystem writes, and do not turn unavailable history fixtures into passing graph_read_exit_code.
- [ ] Run once final covering set: `tests/unit/test_identity_graph_traversal.py`, `tests/unit/test_graph_read.py`, `tests/unit/test_graph_traversal.py`, `tests/unit/test_spec_graph_identity.py`. No unchanged full/million/provider/live or post-commit repeats.
- [ ] Document primary selector precedence and the exact conservative typed impact policy without calling it evidence approval or controller invalidation. Self-review all old map entries/aliases retained, run git diff --check, commit only task files and write full actual RED/GREEN/commands/results in the report. Root owns plan/ledger/checkpoint and independent review.

## Remaining integration

Live managed graph builder/audit/source loading and supported projection-version enforcement remain separate required work, as do managed namespace/run feature snapshots, complete source/semantic/recovery publication, memory current-revision semantics, all producers and bounded repair. These read-only query changes do not authorize publishing a managed graph or passing a stale graph as current completion evidence.
