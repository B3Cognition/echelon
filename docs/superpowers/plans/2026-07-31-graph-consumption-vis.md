# Graph Consumption And Vis Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic graph query and traversal commands over persisted workspace/spec graphs, enrich requirement projection freshness, and provide an offline vis-network renderer alongside Cytoscape.

**Architecture:** A new `graph_read` module owns audit-aware persisted graph loading, structural indexes, and identity resolution. A pure `graph_traversal` module produces shared result objects consumed by thin CLI output adapters, while both HTML renderers consume one renderer-neutral `GraphViewPayload`. Existing miners, MemPalace reconciliation, graph builders, audit authorities, and Cytoscape behavior remain intact.

**Tech Stack:** Python 3.11, frozen dataclasses, Typer, pytest, deterministic JSON, bundled Cytoscape.js 3.34.0, bundled vis-network 10.1.0 standalone UMD, self-contained HTML/JavaScript.

## Global Constraints

- Canonical artifacts remain authoritative; MemPalace remains the semantic index; persisted graphs remain derived indexes.
- `query`, `explain`, `path`, `neighbors`, `impact`, and both renderers are read-only with respect to canonical artifacts, MemPalace, graph JSON, and audit sidecars.
- Workspace graph is the default read scope; `--spec <id>` selects exactly one persisted member graph.
- Structurally valid stale/unhealthy graphs emit results and exit `1`; missing or structurally invalid graphs and unknown/ambiguous identities emit no result and exit `2`.
- Query and traversal are deterministic and use no LLM, embeddings, community detection, graph database, MCP, code mining, PR analysis, automatic rebuild hook, or interactive graph editing.
- Cytoscape remains the default renderer and retains its existing default output filenames and behavior.
- vis-network is pinned to `10.1.0`, bundled locally with MIT and Apache-2.0 notices, and never loaded from a CDN.
- vis-network renders at most 5,000 nodes and 10,000 edges; larger documents receive a complete count/message and no partial graph.
- Real workspace verification must not hard-code spec IDs, room names, artifact counts, or artifact-kind counts from `md_distribution` or `optasearch`.

## File Structure

- Create `src/echelon/graph_read.py`: persisted graph loading, structural validation, indexes, audit-aware scope, identity resolution, and read exit classification.
- Create `src/echelon/graph_traversal.py`: result/path dataclasses and pure explain, neighbors, path, query, and impact algorithms.
- Create `src/echelon/graph_output.py`: common JSON envelope and concise human-readable output.
- Create `src/echelon/graph_vis_network.py`: vis-network asset loading and self-contained HTML rendering.
- Create `src/echelon/assets/vis-network-10.1.0.min.js`: pinned standalone UMD distribution.
- Create `src/echelon/assets/licenses/VIS-NETWORK-LICENSE-MIT.txt`: upstream MIT license.
- Create `src/echelon/assets/licenses/VIS-NETWORK-LICENSE-APACHE-2.0.txt`: upstream Apache-2.0 license.
- Create `src/echelon/assets/licenses/VIS-NETWORK.md`: asset version, upstream URL, integrity, and extraction path.
- Create `tests/unit/test_graph_read.py`: scope loading, structural validation, indexing, audit preservation, and identity resolution.
- Create `tests/unit/test_graph_traversal.py`: deterministic graph operations and limits.
- Create `tests/unit/test_graph_output.py`: JSON/text result contract and stale warnings.
- Create `tests/unit/test_cli_graph_consumption.py`: all five CLI command contracts and exit behavior.
- Create `tests/unit/test_graph_vis_network.py`: offline renderer, controls, escaping, limits, and deterministic payload checks.
- Modify `src/echelon/spec_graph.py`: requirement source projection and projection version emission.
- Modify `src/echelon/spec_graph_audit.py`: projection staleness finding and classification.
- Modify `src/echelon/graph_visualization.py`: delegate structural loading to `graph_read` and build/consume `GraphViewPayload` for Cytoscape.
- Modify `src/echelon/cli_app.py`: register graph consumption commands and renderer selection.
- Modify `tests/unit/test_spec_graph.py`, `tests/unit/test_spec_graph_audit.py`, `tests/unit/test_workspace_graph.py`, `tests/unit/test_graph_visualization.py`, `tests/unit/test_workspace_graph_visualization.py`, `tests/unit/test_cli_graph.py`, and `tests/unit/test_cli_workspace_graph.py`: focused regression coverage.
- Modify `tests/integration/test_workspace_graph_workflow.py`: end-to-end persisted workspace graph consumption and renderer workflow.
- Modify `README.md`: publish, reconcile, build/refresh, consume, and renderer documentation.

---

### Task 1: Version And Audit The Requirement Projection

**Files:**
- Modify: `src/echelon/spec_graph.py`
- Modify: `src/echelon/spec_graph_audit.py`
- Modify: `tests/unit/test_spec_graph.py`
- Modify: `tests/unit/test_spec_graph_audit.py`
- Modify: `tests/unit/test_workspace_graph.py`

**Interfaces:**
- Consumes: `CanonicalRequirement.id`, `.source_text`, `.source_line`, and `.source_kind` from `harness.canonical_requirements.extract_canonical_requirements`.
- Produces: `NODE_PROJECTION_VERSION = 2`, top-level `node_projection_version`, requirement properties `source_text`, `source_path`, and one-based `source_line`, and rebuildable audit code `graph_projection_stale`.

- [ ] **Step 1: Write failing projection tests**

Extend the canonical requirement builder test with these assertions:

```python
payload = graph.to_dict()
assert payload["node_projection_version"] == 2
requirement = next(node for node in payload["nodes"] if node["type"] == "Requirement")
assert requirement["properties"] == {
    "category": "functional",
    "requirement_id": "FR-001",
    "source_line": 3,
    "source_path": "specs/001-demo/spec.md",
    "source_text": "- **FR-001**: Build the report.",
}
```

Add a workspace composition assertion proving these properties survive member normalization unchanged.

- [ ] **Step 2: Write failing projection-audit tests**

Create one stored payload without `node_projection_version` and another with version `2` but missing `source_text`. Assert both audit to `fail`, include exactly one `graph_projection_stale` finding, and classify as `stale`. Assert a current graph passes.

```python
assert "graph_projection_stale" in REBUILDABLE_GRAPH_FINDING_CODES
assert classify_spec_graph_audit(report) == "stale"
```

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py tests/unit/test_workspace_graph.py -q
```

Expected: FAIL because version and source fields are absent and the finding code is unknown.

- [ ] **Step 4: Implement projection version and fields**

In `spec_graph.py`, add:

```python
NODE_PROJECTION_VERSION = 2
```

Emit it from `SpecArtifactGraph.to_dict()`. Populate requirement properties from the canonical row:

```python
{
    "requirement_id": row.id,
    "category": _category_for(row.id),
    "source_path": _workspace_path(root, spec_dir / "spec.md"),
    "source_line": row.source_line,
    "source_text": row.source_text,
}
```

Keep graph schema version `1`; missing projection version is structurally readable implicit version `1`.

- [ ] **Step 5: Implement projection audit**

Add `graph_projection_stale` to `REBUILDABLE_GRAPH_FINDING_CODES`. After parsing stored bytes, compare `int(stored.get("node_projection_version", 1))` to `NODE_PROJECTION_VERSION` and inspect every stored `Requirement` for string `source_text`, string `source_path`, and positive integer `source_line`. Emit one graph-level error finding summarizing the mismatch; do not emit one finding per requirement.

- [ ] **Step 6: Run focused tests**

Run the Step 3 command. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/spec_graph.py src/echelon/spec_graph_audit.py tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py tests/unit/test_workspace_graph.py
git commit -m "Version requirement graph projection"
```

### Task 2: Add The Audit-Aware Graph Read Model

**Files:**
- Create: `src/echelon/graph_read.py`
- Create: `tests/unit/test_graph_read.py`
- Modify: `src/echelon/graph_visualization.py`
- Modify: `tests/unit/test_graph_visualization.py`

**Interfaces:**
- Consumes: `resolve_spec_dir`, `workspace_graph_path`, `audit_spec_graph`, `audit_workspace_graph`, and graph schema `1` documents.
- Produces:

```python
class GraphReadError(RuntimeError): pass
class NodeResolutionError(GraphReadError): pass

@dataclass(frozen=True)
class GraphReadModel:
    scope: str
    graph_hash: str
    document: Mapping[str, object]
    audit: SpecGraphAuditReport | WorkspaceGraphAuditReport
    nodes_by_id: Mapping[str, Mapping[str, object]]
    outgoing: Mapping[str, tuple[Mapping[str, object], ...]]
    incoming: Mapping[str, tuple[Mapping[str, object], ...]]

```

- `read_graph_document(path: Path) -> dict[str, object]`
- `load_graph(project_root: Path, spec_selector: str | None = None) -> GraphReadModel`
- `resolve_node_id(model: GraphReadModel, selector: str) -> str`
- `graph_read_exit_code(model: GraphReadModel) -> int`

- [ ] **Step 1: Write failing structural/index tests**

Use a six-node fixture with deliberately shuffled nodes and edges. Assert `read_graph_document` rejects duplicate node IDs, duplicate `(source, type, target)` edge identities, non-object properties, and missing endpoints. Assert indexes sort edges by `(type, source, target)` and expose immutable tuples.

- [ ] **Step 2: Write failing scope and audit tests**

Monkeypatch existing spec/workspace resolvers and audits. Assert `load_graph(tmp_path)` selects `.echelon/runtime/graph/workspace-artifact-graph.json`; `load_graph(tmp_path, "905")` selects the canonical spec graph; both retain live findings and exact `graph_hash`. Assert no build, refresh, or write function is called.

- [ ] **Step 3: Write failing identity tests**

Cover exact canonical ID, case-insensitive unique `FR-012`, unique identity property, unknown selector, and two specs containing `FR-012`. The ambiguous error must include both bounded canonical candidates in lexical order.

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_graph_read.py tests/unit/test_graph_visualization.py -q
```

Expected: FAIL because `echelon.graph_read` does not exist.

- [ ] **Step 5: Implement structural loading and indexes**

Move the scope-neutral JSON/schema/node/edge validation currently in `graph_visualization.load_graph_document` into `read_graph_document`. Build sorted indexes without mutating the document. Keep `graph_visualization.load_graph_document` as a delegating compatibility wrapper for existing internal callers and tests.

- [ ] **Step 6: Implement scope loading and identity resolution**

Always compute `graph_hash` from exact persisted graph bytes; retain the live audit's own hash in its nested audit payload. Exact IDs win. Shorthand candidates come from the final colon-delimited segment and scalar identity properties ending in `_id`. Reject blank selectors and cap ambiguity output at ten IDs with a remaining-count suffix.

`graph_read_exit_code` returns `0` only for `audit.status == "pass"` with no findings and `1` for every other structurally usable audit result.

- [ ] **Step 7: Run focused tests**

Run the Step 4 command. Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/echelon/graph_read.py src/echelon/graph_visualization.py tests/unit/test_graph_read.py tests/unit/test_graph_visualization.py
git commit -m "Add audit-aware graph reader"
```

### Task 3: Implement Explain, Neighbors, And Shortest Path

**Files:**
- Create: `src/echelon/graph_traversal.py`
- Create: `tests/unit/test_graph_traversal.py`

**Interfaces:**
- Consumes: `GraphReadModel` and canonical node IDs from `graph_read.resolve_node_id`.
- Produces:

```python
@dataclass(frozen=True)
class PathStep:
    source: str
    type: str
    target: str
    direction: str
    properties: Mapping[str, object]

@dataclass(frozen=True)
class GraphPath:
    node_ids: tuple[str, ...]
    steps: tuple[PathStep, ...]

@dataclass(frozen=True)
class GraphResult:
    nodes: tuple[Mapping[str, object], ...]
    edges: tuple[Mapping[str, object], ...]
    paths: tuple[GraphPath, ...]
    truncated: bool = False

```

- `explain_node(model: GraphReadModel, node_id: str, limit: int = 50) -> GraphResult`
- `neighbors(model: GraphReadModel, node_id: str, direction: str = "both", relation: str | None = None, limit: int = 50) -> GraphResult`
- `shortest_path(model: GraphReadModel, source_id: str, target_id: str, max_hops: int = 8) -> GraphResult`

`GraphResult.nodes` is operation-specific: explain and neighbors include the
selected node plus returned adjacent nodes; path includes every path node;
query includes only ranked output-type matches; impact includes only reached
impacted nodes, excluding its starting node. `edges` is the canonical ordered
union of relationships shown directly or used by paths. Evidence paths may
therefore name seed/source nodes that are intentionally not duplicated in
query or impact `nodes`.

- [ ] **Step 1: Write failing explain and neighbor tests**

Assert explain includes the selected node and sorted combined in/out edges. Assert neighbor direction uses stored arrows, relation matching is case-insensitive, absent relation types return empty success, and a limit of one sets `truncated=True` without omitting the selected node.

- [ ] **Step 2: Write failing path tests**

Use a cyclic diamond graph. Assert breadth-first search walks both directions, returns a stable shortest branch under shuffled input order, marks each `PathStep.direction` as `out` or `in`, preserves stored arrows, returns a zero-edge path for identical endpoints, returns empty for no path, and respects `max_hops`.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_graph_traversal.py -q
```

Expected: FAIL because traversal interfaces do not exist.

- [ ] **Step 4: Implement result types and canonical ordering**

Use edge identity `(source, type, target)` for deduplication and output ordering. Apply the operation-specific node semantics above, include only returned relationships in `edges`, and retain persisted node/edge mappings without adding presentation fields.

- [ ] **Step 5: Implement explain and neighbors**

Validate `limit > 0` and direction in `{"both", "in", "out"}`. Apply filters before limits. For `both`, sort by direction (`in` before `out`), relationship type, adjacent ID, then edge identity.

- [ ] **Step 6: Implement deterministic breadth-first path**

Queue `(node_id, GraphPath)` records, maintain visited minimum depth, iterate adjacent steps in `(type, adjacent_id, source, target, direction)` order, and stop after completing the first depth where the target is found.

- [ ] **Step 7: Run focused tests**

Run the Step 3 command. Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/echelon/graph_traversal.py tests/unit/test_graph_traversal.py
git commit -m "Add deterministic graph traversal"
```

### Task 4: Implement Lexical Query And Typed Impact

**Files:**
- Modify: `src/echelon/graph_traversal.py`
- Modify: `tests/unit/test_graph_traversal.py`

**Interfaces:**
- Consumes: `GraphResult`, `GraphPath`, and `GraphReadModel` from Tasks 2-3.
- Produces:

- `query_graph(model: GraphReadModel, question: str, node_type: str | None = None, depth: int = 2, limit: int = 20) -> GraphResult`
- `impact(model: GraphReadModel, node_id: str, max_depth: int = 4, all_relations: bool = False) -> GraphResult`

- [ ] **Step 1: Write failing query tests**

Cover exact ID ranking, exact identity-property ranking, phrase ranking in `source_text`, list/scalar property matching, inferred plural `requirements`, explicit `--type` precedence, absent type, stopword-only input, no matches, bounded expansion evidence paths, deterministic ties, limit truncation, mixed case, punctuation, and Unicode casefolding.

Use the motivating assertion:

```python
result = query_graph(model, "which requirements depend on import validation?")
assert [node["id"] for node in result.nodes] == [
    "req:905-import-prose:FR-012",
]
assert result.paths[0].steps[0].type == "DERIVED_FROM"
```

- [ ] **Step 2: Write failing impact tests**

Build one fixture containing every supported edge type. Assert default impact follows only: reverse `DERIVED_FROM`, reverse `IMPLEMENTS`, forward `VERIFIED_BY`, forward `DEFERRED_BY`, forward `STORED_AS`, forward `HAS_REQUIREMENT`/`AMENDED_BY`/`TARGETS`/`CONTAINS_SPEC`, and reverse `SUPERSEDES`. Assert cycles terminate, shortest evidence paths win, depth truncates visibly, and `all_relations=True` reaches an otherwise excluded neighbor.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_graph_traversal.py -q
```

Expected: FAIL because query and impact functions are absent.

- [ ] **Step 4: Implement deterministic lexical query**

Normalize with Unicode NFKC plus `casefold()`, tokenize alphanumeric/underscore/hyphen identifiers, use a fixed module constant for stopwords and singular/plural node-type aliases, and perform no stemming. Rank with this tuple, negating descending fields before the final lexical ID:

```python
(
    exact_canonical_id,
    exact_identity_property,
    exact_normalized_phrase,
    identity_or_source_token_count,
    other_property_token_count,
    -expansion_depth,
)
```

Expand seeds with deterministic breadth-first traversal through both directions. Return only requested/inferred type nodes when a type filter exists, and retain shortest evidence paths.

- [ ] **Step 5: Implement typed impact traversal**

Encode the approved relation/direction table as one immutable constant keyed by current node type and edge type. Select next steps only when current node type and traversal direction match the table. With `all_relations=True`, use the generic both-direction adjacency iterator from shortest path. Record one shortest path per reached node and set truncation when candidates exist beyond `max_depth`.

- [ ] **Step 6: Run focused tests**

Run the Step 3 command. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/graph_traversal.py tests/unit/test_graph_traversal.py
git commit -m "Add graph query and impact analysis"
```

### Task 5: Expose The Five Consumption Commands

**Files:**
- Create: `src/echelon/graph_output.py`
- Create: `tests/unit/test_graph_output.py`
- Create: `tests/unit/test_cli_graph_consumption.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_graph.py`

**Interfaces:**
- Consumes: `load_graph`, `resolve_node_id`, `graph_read_exit_code`, and all Task 3-4 traversal functions.
- Produces:

- `graph_result_payload(model: GraphReadModel, command: str, request: Mapping[str, object], result: GraphResult) -> dict[str, object]`
- `render_graph_result_text(model: GraphReadModel, command: str, result: GraphResult) -> str`

and the exact CLI commands from the design.

- [ ] **Step 1: Write failing output-contract tests**

Assert JSON has exactly `schema_version`, `scope`, `graph_hash`, `audit`, `command`, `request`, `nodes`, `edges`, `paths`, and `truncated`; path steps include stored arrows plus traversal direction. Assert text starts with scope/audit, prints source path/line, uses `source -[TYPE]-> target` arrows, and prints a truncation notice. Assert hostile property strings remain data under JSON serialization.

- [ ] **Step 2: Write failing CLI help and success tests**

Assert `echelon graph --help` lists `query`, `explain`, `path`, `neighbors`, and `impact`. Monkeypatch only `graph_read.load_graph` and traversal entry points, then verify each example command forwards defaults and emits valid JSON:

```text
echelon graph query "which requirements depend on import validation?"
echelon graph explain req:905-import-prose:FR-012
echelon graph path req:905-import-prose:FR-012 artifact:specs/905-import-prose/spec.md
echelon graph neighbors task:905-import-prose:T-001
echelon graph impact req:905-import-prose:FR-012
```

Add one `--spec 905-import-prose` assertion per loading path, not per command.

- [ ] **Step 3: Write failing CLI error/exit tests**

Assert a healthy empty result exits `0`; a usable graph with a finding prints the warning and result then exits `1`; missing/invalid graph, unknown/ambiguous node, invalid direction, and non-positive limits exit `2` without a JSON envelope. Assert no command calls build, refresh, memory, or graph write functions.

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_graph_output.py tests/unit/test_cli_graph_consumption.py tests/unit/test_cli_graph.py -q
```

Expected: FAIL because output adapters and commands do not exist.

- [ ] **Step 5: Implement JSON and text output**

Serialize audit through its existing `to_dict()`. Serialize each `GraphPath` as `node_ids` and ordered `steps`. Use `json.dumps(payload, indent=2, sort_keys=True)` through the existing CLI JSON helper. Keep text compact and deterministic; never print Python repr for property dictionaries.

- [ ] **Step 6: Register thin Typer commands**

Add five `@graph_app.command` handlers. Resolve scope once, resolve required node selectors, invoke one pure traversal function, output before raising `typer.Exit(code=graph_read_exit_code(model))`, and translate `GraphReadError`, `NodeResolutionError`, traversal validation errors, `OSError`, and `ValueError` to one stderr line plus exit `2`.

- [ ] **Step 7: Run focused tests**

Run the Step 4 command. Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/echelon/graph_output.py src/echelon/cli_app.py tests/unit/test_graph_output.py tests/unit/test_cli_graph_consumption.py tests/unit/test_cli_graph.py
git commit -m "Expose graph consumption commands"
```

### Task 6: Introduce One Renderer-Neutral View Payload

**Files:**
- Modify: `src/echelon/graph_visualization.py`
- Modify: `tests/unit/test_graph_visualization.py`
- Modify: `tests/unit/test_workspace_graph_visualization.py`

**Interfaces:**
- Consumes: validated graph documents, existing lens rules, and `GraphAuditReport`.
- Produces:

```python
@dataclass(frozen=True)
class GraphViewPayload:
    scope: str
    title: str
    audit: Mapping[str, object]
    lenses: tuple[str, ...]
    initial_lens: str
    nodes: tuple[Mapping[str, object], ...]
    edges: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "title": self.title,
            "audit": dict(self.audit),
            "lenses": list(self.lenses),
            "initial_lens": self.initial_lens,
            "nodes": [dict(node) for node in self.nodes],
            "edges": [dict(edge) for edge in self.edges],
        }
```

- `build_graph_view_payload(document: Mapping[str, object], audit: GraphAuditReport, initial_lens: str) -> GraphViewPayload`

- [ ] **Step 1: Write failing shared-payload tests**

Assert each node contains persisted identity/type/properties plus `label`, `searchable_label`, bounded `degree`, `member_specs`, `exception`, and sorted lens membership. Assert each edge contains persisted source/type/target/properties plus sorted lens membership. Assert spec and workspace payloads expose the correct lens lists and initial lens validation.

- [ ] **Step 2: Add Cytoscape regression assertions**

Assert the existing HTML still embeds one payload, all existing controls/lenses remain, malicious `</script>` text is escaped, output is deterministic, and no existing Cytoscape default behavior changes.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_graph_visualization.py tests/unit/test_workspace_graph_visualization.py -q
```

Expected: FAIL because `GraphViewPayload` is absent.

- [ ] **Step 4: Implement the shared payload**

Derive degree from complete directed edges and cap presentation size input at the highest degree rather than changing persisted properties. Reuse `filter_graph` to calculate lens membership so the payload has one authority for current lens semantics. Include `member_specs=()` when absent and convert all output collections to canonical order.

- [ ] **Step 5: Refactor Cytoscape rendering to consume it**

Keep `render_graph_html(document, audit, cytoscape_source, initial_lens)` public signature intact. Build `GraphViewPayload` inside it, then adapt payload nodes/edges to Cytoscape elements. Preserve `window.ECHELON_GRAPH` for existing offline inspection tests.

- [ ] **Step 6: Run focused tests**

Run the Step 3 command. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/graph_visualization.py tests/unit/test_graph_visualization.py tests/unit/test_workspace_graph_visualization.py
git commit -m "Share graph renderer payload"
```

### Task 7: Vendor And Implement The Offline Vis Renderer

**Files:**
- Create: `src/echelon/graph_vis_network.py`
- Create: `src/echelon/assets/vis-network-10.1.0.min.js`
- Create: `src/echelon/assets/licenses/VIS-NETWORK-LICENSE-MIT.txt`
- Create: `src/echelon/assets/licenses/VIS-NETWORK-LICENSE-APACHE-2.0.txt`
- Create: `src/echelon/assets/licenses/VIS-NETWORK.md`
- Create: `tests/unit/test_graph_vis_network.py`
- Modify: `pyproject.toml` only if the existing `assets/*.js` and `assets/licenses/*` package-data rules do not include all four new files.

**Interfaces:**
- Consumes: `GraphViewPayload.to_dict()` from Task 6.
- Produces:

```python
VIS_NETWORK_ASSET = "assets/vis-network-10.1.0.min.js"
VIS_MAX_NODES = 5_000
VIS_MAX_EDGES = 10_000

```

- `load_vis_network_source() -> str`
- `render_vis_graph_html(payload: GraphViewPayload, vis_network_source: str) -> str`

- [ ] **Step 1: Write failing asset and HTML tests**

Assert asset loading succeeds through `importlib.resources`, the source defines `vis.Network`, output contains no external `<script src>` or stylesheet, hostile `</script>` payload values cannot break the data script, and two renders of the same payload are byte-identical.

- [ ] **Step 2: Write failing interaction-contract tests**

Assert HTML contains type/spec grouping, lens and legend filters, search, details, incoming/outgoing neighbor lists, fit/reset controls, physics toggle, directed arrow options, edge labels, audit status/findings, and accessible labels/tooltips. Assert node degree maps to a stable bounded size and no text control changes canvas dimensions.

- [ ] **Step 3: Write failing graph-limit tests**

At exactly 5,000 nodes and 10,000 edges, assert the network initializes. At either limit plus one, assert HTML reports exact counts, names Cytoscape, omits `new vis.Network`, and does not serialize a partial node/edge list.

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_graph_vis_network.py -q
```

Expected: FAIL because the renderer module is absent.

- [ ] **Step 5: Vendor the exact standalone asset and notices**

Use a temporary directory outside the repository:

```bash
VIS_TMP=$(mktemp -d /tmp/echelon-vis-network.XXXXXX)
npm pack vis-network@10.1.0 --pack-destination "$VIS_TMP"
tar -xzf "$VIS_TMP/vis-network-10.1.0.tgz" -C "$VIS_TMP" package/standalone/umd/vis-network.min.js package/LICENSE-MIT package/LICENSE-APACHE-2.0
```

Copy the standalone UMD file and both exact license texts into the paths above. In `VIS-NETWORK.md`, record version `10.1.0`, upstream `https://github.com/visjs/vis-network`, npm integrity `sha512-D7b5p/C6SwWv1BlH9EDdtP0Tje/PJzSBWKef9qy2DyTC14QB7KBcnAZxIyW2m7mFYyfoeR+k5GF747zDcIhaKA==`, and extraction path `package/standalone/umd/vis-network.min.js`.

- [ ] **Step 6: Implement asset loading and safe payload embedding**

Follow the Cytoscape `importlib.resources` loader pattern. Serialize payload with sorted keys and replace `<`, `>`, `&`, U+2028, and U+2029 before insertion into a non-executable JSON data block or assigned JavaScript object.

- [ ] **Step 7: Implement the vis-network interface**

Create one full-width graph canvas plus restrained toolbar/sidebar controls. Use stable group colors spanning multiple hue families, `arrows: {to: {enabled: true}}`, bounded degree sizing, physics stabilization, and deterministic type/spec group keys. Implement filtering by rebuilding DataSets from the single embedded payload. Fit/reset and physics controls use fixed-size buttons with accessible names and hover titles.

- [ ] **Step 8: Run focused tests and package check**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_graph_vis_network.py -q
.venv/bin/python -m build --wheel --outdir /tmp/echelon-wheel
unzip -l /tmp/echelon-wheel/echelon-*.whl | rg 'vis-network|VIS-NETWORK'
```

Expected: tests PASS and wheel listing contains the JS asset and three notice files. If `build` is unavailable, run `.venv/bin/python -m pip wheel . --no-deps -w /tmp/echelon-wheel` instead and record that substitution.

- [ ] **Step 9: Commit**

```bash
git add src/echelon/graph_vis_network.py src/echelon/assets/vis-network-10.1.0.min.js src/echelon/assets/licenses/VIS-NETWORK-LICENSE-MIT.txt src/echelon/assets/licenses/VIS-NETWORK-LICENSE-APACHE-2.0.txt src/echelon/assets/licenses/VIS-NETWORK.md tests/unit/test_graph_vis_network.py pyproject.toml
git commit -m "Add offline vis-network renderer"
```

### Task 8: Wire Renderer Selection Into Both View Commands

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_graph.py`
- Modify: `tests/unit/test_cli_workspace_graph.py`

**Interfaces:**
- Consumes: existing Cytoscape `render_graph_html`, `build_graph_view_payload`, `load_vis_network_source`, and `render_vis_graph_html`.
- Produces: `--renderer cytoscape|vis` on spec and workspace `view`, with Cytoscape default and renderer-specific default paths.

- [ ] **Step 1: Write failing spec-view CLI tests**

Assert no `--renderer` retains `.echelon/graph/<spec>.html` and Cytoscape. Assert `--renderer vis --no-open` writes `.echelon/graph/<spec>-vis.html`, uses the live audit and default traceability/exceptions lens, and does not call the Cytoscape source loader. Assert `--output` overrides both defaults.

- [ ] **Step 2: Write failing workspace-view CLI tests**

Assert vis defaults to `.echelon/runtime/graph/workspace-vis.html`, uses portfolio/exceptions default lens, preserves workspace audit findings, and retains the existing workspace `view` exit mapping for a structurally valid placeholder-only graph. The new usable-stale exit policy applies only to the five consumption commands.

- [ ] **Step 3: Write failing validation/open tests**

Assert unknown renderer exits `2` before writing output; both renderers honor `--open/--no-open`; browser-open failure remains a warning and does not replace graph audit exit status.

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_cli_graph.py tests/unit/test_cli_workspace_graph.py -q
```

Expected: FAIL because `--renderer` is unknown.

- [ ] **Step 5: Implement renderer dispatch**

Add a shared case-insensitive renderer validator returning `cytoscape` or `vis`. Keep current Cytoscape branch byte-for-byte behavior where practical. In the vis branch, build the shared payload once, render with the local asset, and select the approved default filenames. Keep all view commands read-only.

- [ ] **Step 6: Run focused tests**

Run the Step 4 command. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/cli_app.py tests/unit/test_cli_graph.py tests/unit/test_cli_workspace_graph.py
git commit -m "Add graph view renderer selection"
```

### Task 9: Document And Exercise The Complete Workflow

**Files:**
- Modify: `README.md`
- Modify: `tests/integration/test_workspace_graph_workflow.py`

**Interfaces:**
- Consumes: all commands and output paths from Tasks 1-8.
- Produces: user-facing operational documentation and one generic integration workflow.

- [ ] **Step 1: Add the integration workflow**

Extend the existing temporary-workspace integration test to:

1. publish fixture RE/spec/evidence through existing test helpers;
2. refresh the workspace graph with `--write`;
3. query a requirement phrase;
4. explain the returned requirement;
5. find a path to a linked artifact;
6. inspect task neighbors;
7. calculate requirement impact;
8. write both Cytoscape and vis workspace views with `--no-open`;
9. refresh again and assert member graphs and workspace graph are not rewritten.

Derive selectors from fixture output rather than literal production workspace IDs.

- [ ] **Step 2: Run the integration workflow**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_workspace_graph_workflow.py -q
```

Expected: PASS. A failure identifies a missing cross-component contract before
documentation and real-workspace verification.

- [ ] **Step 3: Update README command and workflow documentation**

Document this sequence near the existing graph section:

```bash
echelon spec memory audit <spec>
echelon re memory audit
echelon spec evidence memory audit <spec>
echelon graph workspace refresh --write
echelon graph query "which requirements depend on import validation?"
echelon graph explain req:905-import-prose:FR-012
echelon graph path req:905-import-prose:FR-012 artifact:specs/905-import-prose/inputs/catalog.json
echelon graph neighbors task:905-import-prose:T-001
echelon graph impact req:905-import-prose:FR-012
echelon graph workspace view --renderer cytoscape
echelon graph workspace view --renderer vis
```

Explain workspace-default scope, `--spec`, JSON envelopes, exit `1` with usable stale results, exit `2` without results, explicit refresh recovery, renderer filenames, offline assets, and the vis size boundary. Link the deferred roadmap design rather than copying its table into README.

- [ ] **Step 4: Run integration and graph unit suites**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py tests/unit/test_graph_read.py tests/unit/test_graph_traversal.py tests/unit/test_graph_output.py tests/unit/test_cli_graph_consumption.py tests/unit/test_graph_visualization.py tests/unit/test_workspace_graph_visualization.py tests/unit/test_graph_vis_network.py tests/unit/test_cli_graph.py tests/unit/test_cli_workspace_graph.py tests/integration/test_spec_graph_workflow.py tests/integration/test_workspace_graph_workflow.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/integration/test_workspace_graph_workflow.py
git commit -m "Document graph consumption workflow"
```

### Task 10: Verify Real Workspaces, Browsers, And Full Regression

**Files:**
- Modify only files already owned by this plan if verification exposes a defect.

**Interfaces:**
- Consumes: installed editable Echelon CLI and current persisted state in `/Users/michalbachorik/work/md_distribution` and `/Users/michalbachorik/work/optasearch`.
- Produces: final verification evidence; no fixture-specific production code.

- [ ] **Step 1: Install the branch editable and run full automated verification**

Run:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m pytest tests/unit/ tests/kernel/test_prompt_references.py -q --tb=short
.venv/bin/python -m pytest tests/integration/test_spec_graph_workflow.py tests/integration/test_workspace_graph_workflow.py -q
```

Expected: all tests PASS.

- [ ] **Step 2: Refresh and consume each real workspace generically**

For each workspace root, run the installed executable from that directory:

```bash
echelon graph workspace refresh --write
echelon graph query "requirements import validation" --limit 5 --json
echelon graph workspace view --renderer cytoscape --no-open
echelon graph workspace view --renderer vis --no-open
echelon graph workspace refresh --write
```

Choose one requirement, one task, and one artifact from the first JSON result or the graph document using `jq`, then run `explain`, `neighbors`, `path`, and `impact` with those discovered IDs. Record graph SHA-256 before and after the second refresh and assert equality. A workspace with no lexical match is not a failure; use the first requirement's `source_text` tokens discovered from the graph rather than adding a fixture-specific fallback to Echelon.

- [ ] **Step 3: Browser-check both renderers**

Serve each workspace's generated HTML directory through a temporary local HTTP server. Open Cytoscape and vis outputs at desktop `1440x900` and mobile `390x844`. Verify nonblank graph pixels, fit/reset/search/lens controls, vis physics toggle, node details, directed relationships, audit visibility, no external network requests, no overlapping controls, and readable wrapping. Capture screenshots for review, then stop the server.

- [ ] **Step 4: Inspect final diff and repository state**

Run:

```bash
git diff --check
git status --short
git log --oneline --decorate -12
```

Expected: no whitespace errors; only intentional plan-owned changes remain; each completed task has a focused commit.

- [ ] **Step 5: Close any verification loop**

If Step 1-4 exposes a defect, return to the task that owns that exact file,
apply its test-first correction, rerun that task's focused command plus Step 1,
and commit through that task's explicit file list. When verification is clean,
confirm `git status --short` is empty; do not create an empty commit.
