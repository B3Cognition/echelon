# Identity graph projection implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Project complete retained identity history into the existing graph model without changing published entity keys, losing earlier revision bindings, or labeling old verification as current.

**Architecture:** A pure opt-in projector consumes a fresh base `SpecArtifactGraph` and one same-authority `IdentityHistorySnapshot`. It merges lifecycle metadata into stable entity nodes and adds separately keyed revision, reference, issue-occurrence and source/report-history nodes. It returns a graph value only; existing live builders/auditors/readers and completion publishers are not activated until their subsequent integration is ready.

**Tech Stack:** Existing graph dataclasses/canonical hashes/validation, immutable history JSON, standard-library copying and strict validation, real authority fixtures and pure graph tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing graph keys remain valid.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- Any consumer unable to represent a lifecycle operation must block that operation until its adapter is available, rather than dropping history.
- No live graph builder/audit/read/traversal integration, graph publication, memory writes, controller/provider/producer activation or new database schema in this task.

---

### Task 1: project complete retained history into a fresh graph value

**Files:** Create `src/echelon/spec_graph_identity.py` and `tests/unit/test_spec_graph_identity.py`. Document in `docs/element-identity-storage.md`. Existing graph model/schema, graph builder, audit, read, traversal and storage code remain unchanged. Do not create a second graph writer or expose a CLI command.

**Public interface:**

```python
def project_identity_history(
    graph: SpecArtifactGraph,
    snapshot: IdentityHistorySnapshot,
) -> SpecArtifactGraph: ...
```

Read the exact existing graph dataclasses from `echelon.spec_graph` and the new `harness.element_identity_snapshot` payload contract. Use `SpecGraphError` for malformed projection inputs; validate before returning a partial graph. No filesystem reads, ledger queries/writes, current-store capture, provider calls, memory lookups or output writes. The caller must supply an authenticated snapshot from the intended authority and an independently authenticated source graph; value construction or a self-consistent hash is not authorization. Projection is a derived view, not a substitute for the snapshot's full store audit or canonical-source/semantic review.

**Input checks and ownership:** Require exact `SpecArtifactGraph` and `IdentityHistorySnapshot` types. Revalidate snapshot string fields, exact lowercase SHA-256, actual payload ASCII hash, canonical strict string-tree JSON, exact version-1 root/row key sets from the snapshot plan, canonical UUID strings, exact spec match and string/NULL field types. IDs/revisions/ordinals remain strings, including arbitrarily wide decimal values and exact composite labels. Reuse existing lifecycle/binding validators and `strict_json` for their own formats; do not reimplement the complete SQLite audit. Detect duplicate entity/revision/lineage/binding keys and missing entity/revision targets before building edges. Validate head status/revision against the retained current revision and preserve imported/null heads. Validate source content hashes against UTF-8 revision content and original occurrence fingerprints/binding payload hashes using existing helpers/formulas. Normalize malformed shapes, modified/missing frozen attributes, invalid UTF-8/deep JSON and bad graph fields to bounded `SpecGraphError`; do not leak untrusted full payloads in errors.

Validate the existing graph's normal unique-node/edge/endpoints contract. There must be exactly one Spec node at `spec:<graph.spec_id>`. Consume only a fresh base graph: reject an existing `identity_projection` property on its Spec, `identity_history` input role, generated `identity-` node prefix or any generated history relationship named below. Reject conflicting preexisting entity `identity` properties rather than silently overwriting. Rebuilding uses a fresh source graph and complete history snapshot; applying this helper twice to an already projected value is not its retry interface.

Every retained row's spec_id must equal the root spec. Validate entity labels against kind/ordinal without padding normalization, reject competing numeric padding aliases (same kind/ordinal under different labels), validate revision labels and positive decimal strings, and check head-to-maximum retained revision/status consistency. Imported heads have no revision rows. Nullable fields are only entity ordinal/revision, revision reason and reference target_revision; status/reason combinations keep the existing lifecycle contract. References must target an existing same-spec entity and any non-null revision must exist. Issue occurrences must target an ISS entity and the exact matching historical active subject/body revision. Lineage must connect the existing predecessor active revision and successor active revision 1 with the recorded transition's terminal predecessor and original reason/operation association. These are consistency checks on supplied records, not reconstruction of original SQL request/receipt history or claims of cryptographic authority.

Copy all retained node/edge property trees so input graph mutations cannot affect the result or vice versa. The existing properties interface is Mapping, not necessarily dict: support ordinary read-only mapping proxies as well as nested maps/lists/tuples by detaching their data, rather than requiring every mapping to be pickleable by deepcopy. Keep existing JSON-compatible scalar values unchanged; do not impose identity-payload numeric-string rules on unrelated graph metadata such as source_line. Retain original generator version, memory receipts, inputs, unrelated nodes/edges and all their properties. No current-source assumption may be invented from a ledger source path or a matching display label. Validate the completed graph with the existing graph contract before returning.

**Projection context:** Add exactly this property to the retained Spec node:

```python
"identity_projection": {
    "version": "1", "workspace_uuid": workspace_uuid,
    "epoch_uuid": epoch_uuid, "history_sha256": snapshot.sha256,
}
```

Add one required `GraphInput` with role `identity_history`, hash `sha256:<snapshot.sha256>` and path `identity://<workspace_uuid>/<epoch_uuid>/<URL-quoted-spec-id>` (`urllib.parse.quote(spec_id, safe="")`). Reject a preexisting input at this exact virtual path even if its role differs; do not create conflicting duplicate path entries. This is a virtual history observation, not the digest of mutable registry.sqlite3 bytes. Keep the existing global graph schema/projection versions unchanged; this opt-in component has its own explicit string version, and live consumer support is deliberately not claimed here.

**Stable entities:** Use existing `_scope_node_id(spec_id, label)` keys verbatim: `task:<spec>:<T-label>`, otherwise `req:<spec>:<label>`. Kind/type mapping is FR/NFR/AC -> Requirement, T -> Task, U -> Unknown, A -> Assumption, ISS -> Issue. Existing nodes at these keys must have the expected type. Every preexisting node of these entity types must correspond to an exact retained entity and consistent human label property (requirement_id/task_id/element_id according to the mapping); missing/unallocated or conflicting identity is an error, not a newly imported row. Missing retained entities get new nodes, including terminal and unassessed ones; preserve all seven families, not only current Markdown requirements.

Merge one `identity` property into each entity node with exact keys `workspace_uuid`, `epoch_uuid`, `kind`, `ordinal`, `subject`, `status`, `revision`, `rendered`. `rendered` is true only if that entity node existed in the supplied base graph; it is not semantic/current-source certification. Do not overwrite existing task-progress `status`, source_text, source_path or source_line. For newly added nodes use only the usual human label property (`requirement_id` for FR/NFR/AC, `task_id` for T, `element_id` otherwise), plus `identity`; do not fabricate source lines, task progress or current Markdown bytes. Add Spec -> HAS_IDENTITY -> entity for every retained entity, regardless of any preexisting HAS_REQUIREMENT edge.

**Generated history keys:** Use existing `_canonical_digest` of the exact arrays below, remove its `sha256:` prefix and prepend the specified node prefix. Each array starts with `[workspace_uuid, epoch_uuid, spec_id]`. Keys depend on immutable identity/provenance, not the whole history hash or current lifecycle state:

- `identity-revision:` + digest(namespace + [element_id, revision]) -> type `ElementRevision`.
- `identity-reference:` + digest(namespace + [operation_id, entry_index]) -> type `ReferenceClaim`.
- `identity-occurrence:` + digest(namespace + [operation_id, entry_index]) -> type `IssueOccurrence`.
- `identity-source:` + digest(namespace + [source_path, source_sha256]) -> type `IdentitySource`.
- `identity-report:` + digest(namespace + [report_id, report_sha256]) -> type `IdentityReport`.

All records with the same source/report key share one node only when their properties agree exactly. A generated key collision with another generated meaning or any retained base node fails; no overwrite or deduplication that drops an occurrence.

**Revisions and lineage:** Each ElementRevision node carries all exact snapshot revision-row properties. Add entity -> HAS_REVISION -> each revision; add entity -> CURRENT_REVISION -> its head revision if non-null. All historical content, status, reason and operation IDs remain original. Add predecessor active revision -> SUCCESSOR_REVISION -> successor creation revision for every lineage row; edge properties are the complete original lineage row, including kind/reason/operation_id. Existing lineage pairs are unique; do not collapse split/merge rows or place alternate histories on duplicate edge triples. Terminal revisions are retained independently of lineage edges.

**Reference history:** Each ReferenceClaim node carries every exact snapshot row field plus `target_revision_matches_current`, true only for a non-null assessed revision equal to an active head. This boolean describes the retained target binding, not source freshness or verified completion. Add claim -> REFERENCES_IDENTITY -> entity. For non-null target_revision, also add claim -> ASSESSES_REVISION -> exact revision. Add claim -> HAS_SOURCE -> IdentitySource with exact properties `spec_id`, `source_path`, `source_sha256`. No source bytes, physical-path mapping, current-Artifact link or evidence verdict is fabricated. Null references remain unassessed and do not acquire an assessed-revision edge.

**Issue occurrences:** Each IssueOccurrence node carries every exact snapshot occurrence-row property. Add occurrence -> OCCURRENCE_OF -> Issue entity, occurrence -> OBSERVES_REVISION -> its exact historical active revision, and occurrence -> HAS_REPORT -> IdentityReport with exact `spec_id`, `report_id`, `report_sha256` properties. Preserve display ID, title/body and fingerprint exactly. Do not infer report file paths or merge two distinct operations merely because a report/display ID matches.

**Legacy verification:** Retain existing VERIFIED_BY and STORED_AS edge endpoints and all original properties, but add `identity_assessment: "unassessed"` to those touching a managed entity. Reject a conflicting preexisting `identity_assessment` property rather than accepting it as proof. Do not change an original `complete` field or silently upgrade it to assessed evidence; the subsequent lifecycle-aware audit must explicitly stop counting an unassessed edge as current verification. Existing graph consumers do not yet implement this contract, so no live producer may publish/use this output until their adapter phase is complete.

**First regression:**

```python
def test_retirement_keeps_published_key_old_revision_and_reference_edge(tmp_path):
    # Use real IdentityStore reserve/create/reference/revise/retire and capture,
    # as in test_element_identity_snapshot; no fabricated history or audit stub.
    store, label = retained_history_fixture(tmp_path)
    from echelon.spec_graph import GraphNode, SpecArtifactGraph
    base = SpecArtifactGraph("demo", "test", (), (
        GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),
        GraphNode(f"req:demo:{label}", "Requirement", {"requirement_id": label}),
    ), (), ())
    from echelon.spec_graph_identity import project_identity_history
    projected = project_identity_history(base, store.identity_history(spec_id="demo"))
    nodes = {node.id: node for node in projected.nodes}
    assert nodes[f"req:demo:{label}"].properties["identity"]["status"] == "retired"
    old = next(node for node in projected.nodes if node.type == "ElementRevision"
               and node.properties["revision"] == "1")
    claim = next(node for node in projected.nodes if node.type == "ReferenceClaim")
    assert old.properties["content"] == "Original body"
    assert claim.properties["target_revision_matches_current"] is False
    assert any(edge.source == claim.id and edge.type == "ASSESSES_REVISION"
               and edge.target == old.id for edge in projected.edges)
```

Implement `retained_history_fixture` locally with actual existing APIs: initialize tmp_path, reserve one FR under spec demo/op reserve, create subject Scene/content Original body under op create; record ReferenceClaim(evidence.md, a*64, span:0:9, label, "1", evidence) under op evidence; revise expected "1" to Revised body under op revise, then retire expected "2" with reason No longer an active obligation under op retire. Return store,label. The required first failure must reach the new missing module after valid real fixture setup, before production edits.

- [ ] Add the marked first regression, retain actual RED, implement minimal projection, verify GREEN.
- [ ] Cover exact context/input/node/edge key sets, stable legacy FR-001/composites, all seven kinds, numeric labels at 999999/1000000 and 5,000-digit string IDs/revisions. Test no task-progress/source property overwrite, imported/null heads, absent terminal nodes, all transition kinds and complete predecessor/successor rows.
- [ ] Compare rendered old/new projections after later revisions and additional claims: original history node IDs/properties and binding edge endpoints remain exact, head/current-match metadata changes, and unrelated reservations/publication release keep the history input hash unchanged. Multiple claims/occurrences on the same entity and different revisions must survive without duplicate triples; repeated source/report provenance shares the appropriate snapshot node only.
- [ ] Test null/unassessed references, old active issue occurrences after retirement, exact fingerprints, and original legacy VERIFIED_BY complete/STORED_AS properties retained with explicit unassessed metadata. No test may claim a low-level relation string authenticates verification or current source content.
- [ ] Reject corrupt hash, noncanonical/duplicate/numeric/malformed/deep JSON, wrong root/row shapes, malformed namespace UUIDs or mismatched spec, invalid/missing/null required fields, bad stored content/payload/fingerprint digest, duplicate or dangling records, incompatible existing nodes, generated collisions and already projected inputs. A valid foreign namespace cannot be distinguished without an externally expected authority; authenticate that association in the future caller, not by claiming this pure function proves it. Show no caller graph/property mutation after failures or success, including nested property lists/maps; no filesystem or storage change.
- [ ] Run once final covering modules `tests/unit/test_spec_graph_identity.py`, `tests/unit/test_spec_graph.py`, `tests/unit/test_spec_graph_audit.py`, `tests/unit/test_graph_read.py`, `tests/unit/test_graph_traversal.py`, and `tests/unit/test_element_identity_snapshot.py`. No unchanged million/full repository/provider/live run or post-commit repeat. If an exact listed existing test path is absent, report the concrete corresponding existing module before substituting it.
- [ ] Document projection schema, exact stable/new keys, snapshot provenance limits and blocked live consumer integration. Self-review key and edge uniqueness/history retention, run git diff --check, commit only task files and retain full actual commands/RED/GREEN/results in report. Root owns plan/ledger and independent review.

## Remaining integration

The subsequent existing-builder/audit/read/traversal adapter must authenticate the managed namespace/current history and source inputs, preserve direct bare-ID entity resolution despite new history rows, implement lifecycle-aware obligations/current verification, and include all new typed impact relationships. The stored projection tag is not the immutable managed-spec/run feature snapshot. Complete source/semantic/recovery/completion integration, memory current-revision semantics, all producers and bounded repair remain required. No claim of passing live graph audit or end-to-end publication is made by this pure projection phase.
