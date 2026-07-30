# Spec Artifact Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and audit a deterministic, spec-scoped artifact graph over canonical specification artifacts, native MemPalace planners/audits, amendments, deferrals, tasks, and verification evidence.

**Architecture:** Canonical disk parsers and native memory planners remain authorities. Focused source adapters produce immutable graph inputs, nodes, edges, and memory receipts; a deterministic renderer hashes and writes the graph; a separate auditor rediscovers current state and reports graph and MemPalace staleness independently. Typer commands expose build, audit, and refresh without mining memory.

**Tech Stack:** Python 3.11, frozen dataclasses, SHA-256, canonical JSON, Typer, pytest.

## Global Constraints

- Canonical disk artifacts remain the source of truth.
- MemPalace remains a derived semantic index.
- Graph commands never mine MemPalace or recursively crawl arbitrary workspace files.
- Reuse existing Echelon parsers, ledgers, discovery functions, planners, and audits.
- Graph output is deterministic and generic over discovered rooms and artifact kinds.
- V1 writes JSON only and introduces no graph database or GraphRAG query behavior.
- Preserve unrelated uncommitted RE/evidence audit work in the current workspace.

---

### Task 1: Canonical RE Provenance

**Files:**
- Modify: `src/harness/published_re_context.py`
- Modify: `src/harness/squad.py`
- Test: `tests/unit/test_published_re_context.py`

**Interfaces:**
- Consumes: the existing run-local `published_re_context` mapping returned by `attach_published_re_context`.
- Produces: `write_canonical_re_context(project_root: Path, spec_dir: Path, context: Mapping[str, object]) -> Path`, writing `specs/<id>/re-context.json`.

- [ ] **Step 1: Write failing provenance tests**

Add tests proving that attached context writes sorted workspace-relative `re/...` paths and SHA-256 hashes, ignored/absent states write no artifact rows, and paths outside the immutable snapshot root are rejected.

```python
payload = json.loads(write_canonical_re_context(root, spec_dir, context).read_text())
assert payload == {
    "schema_version": 1,
    "status": "attached",
    "generation": 7,
    "artifacts": [{"path": "re/workspace/overview.md", "hash": "sha256:..."}],
}
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest -q tests/unit/test_published_re_context.py`

Expected: failure because `write_canonical_re_context` does not exist.

- [ ] **Step 3: Implement deterministic provenance publication**

Flatten only absolute artifact file paths below `snapshot_root`, map each to `re/<relative-path>`, hash the snapshot bytes, sort by path, and write canonical JSON with a trailing newline. Preserve `status` as `attached`, `ignored`, or `absent`; omit run-local paths and copied content.

- [ ] **Step 4: Wire Phase A publication**

In the existing Phase A finalization path, call `write_canonical_re_context` after the canonical spec directory is published and before readiness completion. Use the already-attached `state["published_re_context"]`; do not rediscover current RE.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_published_re_context.py tests/unit/test_squad*.py`

Commit:

```bash
git add src/harness/published_re_context.py src/harness/squad.py tests/unit/test_published_re_context.py
git commit -m "Publish canonical RE provenance"
```

---

### Task 2: Deterministic Graph Contract and Canonical Sources

**Files:**
- Create: `src/echelon/spec_graph.py`
- Test: `tests/unit/test_spec_graph.py`

**Interfaces:**
- Produces: `GraphInput`, `GraphNode`, `GraphEdge`, `SpecArtifactGraph`, `build_spec_graph(project_root: Path, selector: str | Path) -> SpecArtifactGraph`, `write_spec_graph(graph: SpecArtifactGraph, spec_dir: Path) -> Path`.
- `SpecArtifactGraph.to_dict()` returns exactly `schema_version`, `generator_version`, `spec_id`, `source_set_digest`, `memory_state_digest`, `inputs`, `nodes`, and `edges`.

- [ ] **Step 1: Write failing deterministic contract tests**

Cover canonical JSON ordering, stable node and edge IDs, duplicate node rejection, duplicate `(source, type, target)` rejection, missing endpoint rejection, and source-set digest changes for added, removed, and modified inputs.

```python
assert [node["id"] for node in payload["nodes"]] == sorted(node["id"] for node in payload["nodes"])
assert payload["source_set_digest"].startswith("sha256:")
assert render_graph(graph) == render_graph(graph)
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest -q tests/unit/test_spec_graph.py`

Expected: import failure for `echelon.spec_graph`.

- [ ] **Step 3: Implement immutable graph records and canonical rendering**

Use frozen dataclasses. Hash canonical JSON with `sort_keys=True` and compact separators. Serialize written graph JSON with sorted keys, indentation, and one trailing newline. Sort inputs by `(role, path)`, nodes by `id`, and edges by `(source, type, target)`.

- [ ] **Step 4: Implement canonical source discovery**

Resolve the spec with `mempalace_requirements.resolve_spec_dir`. Create:

- one `Spec` node using `artifact_index.infer_lifecycle_stage`;
- `Requirement` nodes only for IDs whose first canonical occurrence from `extract_canonical_requirements` has `source_kind == "spec"`;
- `Task` nodes from validated `tasks.md` rows and `IMPLEMENTS` edges to current requirements;
- `Artifact` nodes for existing registered top-level artifacts, input control files, promoted amendment control files, canonical `re-context.json`, evidence discovery results, and every source returned by an applicable native memory planner;
- `Deferral` nodes/edges from `deferred_scope.read_ledger`;
- promoted `Amendment` nodes/edges from sorted `amendments/<revision>/` directories;
- `VERIFIED_BY` edges from `read_verified_ledger`, with `complete` determined only by `UNRESOLVED_STATUSES`;
- `DERIVED_FROM` edges from valid `inputs/traceability.json` requirement-to-input mappings.

Do not create nodes for missing files or requirement references found only in plan, coverage, or task metadata.

- [ ] **Step 5: Add canonical-source behavior tests**

Test acceptance-category IDs, task mappings, unknown requirement references, deferrals, amendments, ledger completeness independent of evidence memory, planner-only supporting artifacts, and deterministic repeated builds.

- [ ] **Step 6: Verify and commit**

Run: `pytest -q tests/unit/test_spec_graph.py`

Commit:

```bash
git add src/echelon/spec_graph.py tests/unit/test_spec_graph.py
git commit -m "Build canonical spec artifact graph"
```

---

### Task 3: Native MemPalace Drawer Reconciliation and Receipts

**Files:**
- Modify: `src/echelon/spec_graph.py`
- Test: `tests/unit/test_spec_graph.py`

**Interfaces:**
- Consumes: `audit_spec_memory`, `audit_re_memory`, `audit_spec_evidence_memory`; corresponding snapshot loaders and native planner methods.
- Produces: expected `MemPalaceDrawer` nodes, `STORED_AS` edges, per-domain audit inputs, and `memory_state_digest`.

- [ ] **Step 1: Write failing memory-domain tests**

Use fake adapters/audit reports to cover:

- every expected planner row becoming one drawer node;
- present/pass, missing/fail, and unavailable states;
- extra drawers remaining findings rather than nodes;
- canonical, evidence, and selected RE domains remaining independent;
- unknown rooms and kinds preserved;
- memory-state digest changing when source-set or normalized audit state changes.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest -q tests/unit/test_spec_graph.py -k 'memory or drawer or receipt'`

Expected: missing drawer and receipt behavior.

- [ ] **Step 3: Implement domain adapters**

For each applicable domain:

1. Load native snapshots.
2. Invoke the native planner for each snapshot.
3. Invoke the native audit once.
4. Normalize only schema, wing, status, artifact/expected/present counts, and sorted issue/error lists.
5. Hash the domain source set and normalized audit.
6. Add the virtual `mempalace://.../audit` input.
7. Create expected drawer nodes and storage edges with row-level `presence`, `reconciliation_status`, and issue codes.

Project the workspace-wide RE audit to drawer IDs planned from artifacts named by canonical `re-context.json`. Do not let unrelated RE findings affect a spec graph.

- [ ] **Step 4: Handle unavailable memory without aborting structural build**

If a collection or adapter is unavailable after native source discovery succeeds, retain expected drawer nodes with `presence: unavailable`, receipt status `unavailable`, and deterministic error codes. Malformed canonical disk artifacts continue to raise `SpecGraphError`.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_spec_graph.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_re.py tests/unit/test_mempalace_spec_evidence.py`

Commit:

```bash
git add src/echelon/spec_graph.py tests/unit/test_spec_graph.py
git commit -m "Reconcile MemPalace in spec graph"
```

---

### Task 4: Graph Audit and Freshness

**Files:**
- Create: `src/echelon/spec_graph_audit.py`
- Test: `tests/unit/test_spec_graph_audit.py`

**Interfaces:**
- Consumes: `build_spec_graph`, canonical graph JSON, current native source discovery and audits.
- Produces: `GraphFinding`, `SpecGraphAuditReport`, `audit_spec_graph(project_root: Path, selector: str | Path) -> SpecGraphAuditReport`, `write_spec_graph_audit(report: SpecGraphAuditReport, spec_dir: Path) -> Path`.

- [ ] **Step 1: Write failing audit status and freshness tests**

Cover:

- `pass`, `warn`, `fail`, and `unavailable`;
- stable finding IDs `finding:<code>:<subject-or-graph>`;
- graph hash over exact graph bytes;
- added, removed, modified, and applicability-changed inputs;
- stale MemPalace and stale graph reported independently;
- refreshed memory with an old graph reported as graph-only stale;
- lifecycle task/verification coverage;
- deferred coverage warnings and unknown IDs;
- malformed graph, duplicate endpoints, and missing graph.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest -q tests/unit/test_spec_graph_audit.py`

Expected: import failure for `echelon.spec_graph_audit`.

- [ ] **Step 3: Implement deterministic audit report**

Read the exact stored graph bytes, validate schema and graph integrity, rebuild current state in memory, compare `source_set_digest` and `memory_state_digest`, then emit artifact-specific diagnostics by comparing input identities and hashes. Merge duplicate code/subject findings and sort by ID.

- [ ] **Step 4: Implement coherence and lifecycle findings**

Report unknown requirement mappings, active requirement task gaps from lifecycle `build`, verification gaps from `verified`, stale/unavailable memory domains, invalid deferrals, and current requirements changed by amendments. Deferred active coverage gaps remain warnings.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py`

Commit:

```bash
git add src/echelon/spec_graph_audit.py tests/unit/test_spec_graph_audit.py
git commit -m "Audit spec graph freshness"
```

---

### Task 5: CLI Build, Audit, and Refresh

**Files:**
- Modify: `src/echelon/cli_app.py`
- Create: `tests/unit/test_cli_spec_graph.py`

**Interfaces:**
- Produces:
  - `echelon spec graph build <selector> [--write]`
  - `echelon spec graph audit <selector> [--json] [--write]`
  - `echelon spec graph refresh <selector> [--write]`

- [ ] **Step 1: Write failing CLI tests**

Cover JSON-only output, text summaries, write/no-write behavior, refresh calling build then audit without mining, selector/parser errors returning `2`, audit fail returning `1`, and pass/warn returning `0`.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest -q tests/unit/test_cli_spec_graph.py`

Expected: Typer reports that `spec graph` does not exist.

- [ ] **Step 3: Add the Typer command group**

Register `spec_graph_app` beneath `spec_app`. Commands call Python APIs directly. `build --write` writes only `spec-artifact-graph.json`; `audit --write` writes only `spec-artifact-graph-audit.json`; `refresh --write` writes both. No command invokes any memory mine or refresh API.

- [ ] **Step 4: Implement bounded CLI rendering and exit codes**

Text output reports spec, graph status, memory status, node/edge counts, and concise findings. JSON mode emits only canonical report JSON. Map `pass` and `warn` to `0`, `fail` to `1`, and unavailable/selector/parser errors to `2`.

- [ ] **Step 5: Run focused and regression tests**

Run:

```bash
pytest -q \
  tests/unit/test_cli_spec_graph.py \
  tests/unit/test_spec_graph.py \
  tests/unit/test_spec_graph_audit.py \
  tests/unit/test_cli_re_memory.py \
  tests/unit/test_cli_spec_evidence_memory.py
```

- [ ] **Step 6: Run the full unit suite**

Run: `pytest -q tests/unit`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/cli_app.py tests/unit/test_cli_spec_graph.py
git commit -m "Expose spec artifact graph CLI"
```

---

### Task 6: Generic Integration Smoke

**Files:**
- Create: `tests/integration/test_spec_graph_workflow.py`
- Modify: `docs/superpowers/specs/2026-07-28-spec-artifact-graph-design.md`

**Interfaces:**
- Consumes: public CLI and graph JSON contracts.
- Produces: a fixture-independent smoke proving normal-pipeline behavior.

- [ ] **Step 1: Add a temporary-workspace integration test**

Create a canonical spec dynamically with requirements, tasks, a planner-only supporting artifact, deferral, amendment, and verification ledger. Stub only the external MemPalace collection boundary; use real Echelon parsers and graph APIs.

- [ ] **Step 2: Exercise the freshness sequence**

Assert:

1. reconciled memory plus graph build audits pass;
2. changing `spec.md` makes memory and graph stale;
3. refreshing the fake memory state without rebuilding leaves only graph stale;
4. graph refresh restores pass.

- [ ] **Step 3: Run integration and full unit verification**

Run:

```bash
pytest -q tests/integration/test_spec_graph_workflow.py
pytest -q tests/unit
```

- [ ] **Step 4: Mark implementation status**

Append an implementation note to the design with the public modules, commands, and verification commands. Do not expand v1 scope.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_spec_graph_workflow.py docs/superpowers/specs/2026-07-28-spec-artifact-graph-design.md
git commit -m "Verify spec graph workflow"
```
