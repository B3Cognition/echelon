# Graph Consumption And Vis Renderer Design

**Status:** Approved for implementation

**Date:** 2026-07-31

## Goal

Make persisted Echelon artifact graphs useful from the CLI for deterministic
search, explanation, traversal, and impact analysis, and add a second offline
interactive renderer based on vis-network.

The feature consumes the existing per-spec and workspace graph artifacts. It
does not introduce another miner, another source of truth, or automatic graph
mutation. Canonical artifacts remain authoritative, MemPalace remains the
semantic index, and graph audit remains the freshness and coherence gate.

## V1 Boundary

V1 adds:

- workspace-default graph query, explain, path, neighbors, and impact commands;
- optional `--spec <id>` scope for the same commands;
- deterministic lexical retrieval and bounded graph expansion;
- canonical requirement text and line metadata in newly built graph nodes;
- audit detection for graphs built with an outdated node projection;
- a shared renderer-neutral view payload;
- an offline vis-network renderer alongside the existing Cytoscape renderer;
- documentation and smoke coverage for the complete publish-to-consume flow.

V1 does not change canonical authority, mine or refresh MemPalace, build graphs
from read commands, or make query results part of persisted graph state.

## Authority And Read Flow

Read commands use only a persisted graph and a live graph audit:

```text
canonical RE/spec/evidence
    -> native MemPalace reconciliation
    -> persisted per-spec graphs
    -> persisted workspace graph
    -> audit-aware read/traversal service
    -> CLI result or renderer payload
```

The default scope is the persisted workspace graph because it avoids manual
per-spec invocation and enables cross-spec paths. `--spec <id>` resolves and
loads that spec's persisted graph instead. Read commands never fall back from a
missing workspace graph to a collection of per-spec graphs; the recovery path
is the existing explicit workspace refresh.

## Architecture

### Graph Read Service

Add a focused `echelon.graph_read` module responsible for:

- resolving workspace or spec scope;
- running the existing live audit for that scope;
- loading and structurally validating the persisted graph;
- indexing nodes, incoming edges, and outgoing edges;
- resolving canonical or shorthand node identities;
- producing a shared audit-aware result envelope.

The loader accepts a structurally valid graph even when its live audit reports
staleness or other non-structural findings. It rejects missing, malformed, or
contract-invalid graph documents before traversal.

Node resolution first attempts an exact canonical node ID. Otherwise, it
matches a case-insensitive unique terminal identity or native identity property
such as `requirement_id` or `task_id`. Multiple matches are an error that lists
bounded candidate canonical IDs; no candidate is chosen heuristically.

### Graph Traversal Service

Add `echelon.graph_traversal` for pure, deterministic operations over the
validated read model:

- lexical query and bounded expansion;
- node explanation;
- directional neighborhood selection;
- shortest-path search;
- typed impact traversal.

It has no dependency on CLI formatting, graph mining, MemPalace writes, an LLM,
or a graph database. Results contain existing persisted nodes and edges plus
derived path information; ranking, paths, and presentation metadata are never
written back to the canonical graph.

### Requirement Projection

Newly built `Requirement` nodes add canonical fields already available from the
shared requirement extractor:

```json
{
  "source_text": "The system shall ...",
  "source_path": "specs/905-import-prose/spec.md",
  "source_line": 42
}
```

`source_text` is the complete canonical requirement row, not MemPalace search
content. `source_line` is one-based. Existing requirement identity and category
properties remain unchanged.

New graphs record top-level `node_projection_version: 2`; a missing field is
treated as the existing implicit version `1`. The structural loader accepts
both versions so an old graph remains inspectable. The spec graph audit emits a
rebuildable `graph_projection_stale` finding when the recorded version is not
the current version or required projected fields are absent. The existing graph
refresh rebuilds it; read commands do not. Workspace audit continues to detect
changed member graph bytes and therefore requires composition after affected
member graphs are rebuilt.

## CLI Contract

Add these top-level graph consumption commands:

```bash
echelon graph query <question> [--spec <id>] [--type <type>] [--depth 2] [--limit 20] [--json]
echelon graph explain <node> [--spec <id>] [--limit 50] [--json]
echelon graph path <source> <target> [--spec <id>] [--max-hops 8] [--json]
echelon graph neighbors <node> [--spec <id>] [--direction both|in|out] [--relation <type>] [--limit 50] [--json]
echelon graph impact <node> [--spec <id>] [--max-depth 4] [--all-relations] [--json]
```

Options reject negative or zero limits and depths. Node and relationship type
filters match case-insensitively; a type absent from the selected graph produces
an empty result rather than an argument error. No compatibility aliases or
nested workspace variants are added.

### Query

`query` is deterministic lexical retrieval followed by bounded graph
expansion. It:

1. normalizes case and token boundaries in the question;
2. recognizes node-type words such as `requirements` as an output filter;
3. removes a small, fixed set of query stopwords;
4. matches canonical IDs, identity properties, `source_text`, and then other
   scalar or list properties;
5. expands seed matches through incoming and outgoing edges up to `--depth`;
6. returns matching output nodes with their shortest evidence paths.

Explicit `--type` takes precedence over a type inferred from the question.
Ranking is a stable tuple in this order: exact canonical ID, exact identity
property, exact normalized phrase, number of query tokens matched in identity
or source text, number matched in other properties, shortest expansion depth,
then canonical node ID. This defines deterministic ties without assigning
opaque relevance scores.

An empty normalized query or no matches is a successful empty result. Expansion
does not turn every reached node into a result: it supplies evidence paths to
nodes satisfying the requested or inferred output type. `--limit` applies to
result nodes after ranking; all edges required by returned evidence paths are
retained.

### Explain

`explain` returns the resolved node, all persisted properties, and bounded
incoming and outgoing relationships. Relationship entries include direction,
type, the adjacent node's canonical ID and type, and edge properties. The limit
applies to the combined relationship list after deterministic ordering.

### Path

`path` uses deterministic breadth-first search over incoming and outgoing
relationships by default. Traversal may walk against a stored edge, but output
always preserves and displays the stored source, type, and target arrow. Among
equal-length paths, canonical edge ordering selects one stable result. Source
equal to target returns a zero-edge path. No path is a successful empty result.

### Neighbors

`neighbors` returns one-hop relationships using `both` by default. `in` and
`out` refer to stored edge direction. `--relation` filters the stored edge type.
Ordering is direction, relationship type, adjacent node ID, then canonical edge
identity. The limit applies after filtering and reports truncation.

### Impact

Default impact analysis follows only relationships whose authority supports a
meaningful downstream interpretation:

| From | To | Traversal |
| --- | --- | --- |
| `Artifact` | `Requirement` | reverse `DERIVED_FROM` |
| `Requirement` | `Task` | reverse `IMPLEMENTS` |
| `Requirement` | verification `Artifact` | forward `VERIFIED_BY` |
| `Requirement` or `Task` | `Deferral` | forward `DEFERRED_BY` |
| source node | `MemPalaceDrawer` | forward `STORED_AS` |
| `Spec` | requirements, amendments, targets | forward corresponding typed edges |
| `Workspace` | `Spec` | forward `CONTAINS_SPEC` |
| superseded `Spec` | superseding `Spec` | reverse `SUPERSEDES` |

Traversal continues from reached nodes using the same table up to
`--max-depth`, records the shortest evidence path to each result, and is
cycle-safe. `--all-relations` is an explicit diagnostic escape hatch that
traverses all stored relationships in both directions. It is not the default
because undirected reachability is not equivalent to impact.

## Result And Error Contract

Human-readable output starts with graph scope and audit state, then prints
concise node identities, source references where available, relationship
arrows, and evidence paths. A stale result is clearly marked before result
content.

Every command supports `--json` with a common envelope:

```json
{
  "schema_version": 1,
  "scope": "workspace",
  "graph_hash": "sha256:...",
  "audit": {"status": "pass", "findings": []},
  "command": "path",
  "nodes": [],
  "edges": [],
  "paths": [],
  "truncated": false
}
```

Command-specific request metadata is included under `request`. Nodes and edges
retain their persisted representation. Paths contain ordered node IDs and
ordered directed edge identities, plus traversal direction for each step.

Exit codes are:

- `0`: the graph is healthy and the command completed, including no matches or
  no path;
- `1`: the graph is structurally usable but its audit is stale, failed, or has
  findings; results are still emitted;
- `2`: the graph is missing or structurally invalid, an identity is unknown or
  ambiguous, or arguments are invalid; no result envelope is emitted.

All bounded output reports `truncated: true` and a human-readable truncation
notice when applicable. Commands never silently discard results and never
refresh memory or rebuild a graph.

## Renderer Contract

Extend the existing commands:

```bash
echelon graph view <spec> [--renderer cytoscape|vis]
echelon graph workspace view [--renderer cytoscape|vis]
```

All existing `--lens`, `--output`, and `--open/--no-open` behavior remains.
Cytoscape remains the default to preserve current behavior.

Both renderers consume one `GraphViewPayload` derived from the same validated
graph and live audit. The payload contains nodes, directed edges, audit state,
lens membership, exception membership, degree data, member specs, and
searchable labels. Renderer-specific layout state does not enter this payload
or persisted graph JSON.

The current Cytoscape implementation remains one renderer. Add a separate
`echelon.graph_vis_network` renderer using a pinned, locally bundled
vis-network 10.1.0 browser asset. Runtime output is self-contained and contains
no CDN dependency. Distribution includes the applicable MIT/Apache license
notices.

The vis renderer provides:

- force-directed physics and stabilization;
- stable node sizing based on bounded degree;
- deterministic grouping by node type, or member spec for workspace views;
- the existing lens choices and audit presentation;
- legend filtering and node/property search;
- node details with incoming and outgoing neighbors;
- fit, reset, and physics toggle controls;
- directed arrows and relationship labels.

V1 uses deterministic type/spec grouping, not inferred communities. A vis view
with more than 5,000 nodes or 10,000 edges writes a clear bounded-size message
that reports both counts and points operators to the Cytoscape renderer; it does
not partially render the graph. These initial limits are constants covered by
boundary tests and can be revised from measured browser results without
changing the graph or CLI contract.

Default Cytoscape output paths remain unchanged. Without `--output`, vis uses:

```text
.echelon/graph/<spec-id>-vis.html
.echelon/runtime/graph/workspace-vis.html
```

This allows both views to coexist. Selecting a renderer never mutates the graph
or audit artifacts.

## Testing And Verification

Unit and CLI tests cover:

- workspace-default and `--spec` loading;
- exact, shorthand, unknown, and ambiguous node resolution;
- deterministic lexical ranking, inferred and explicit types, and no matches;
- cycles, equal shortest paths, reverse traversal, and preserved arrows;
- neighbor direction and relationship filters;
- typed impact traversal and `--all-relations`;
- depth, hop, result, and relationship limits with visible truncation;
- healthy, stale, malformed, and missing graph exit behavior;
- requirement source projection and `graph_projection_stale` recovery;
- common JSON envelope stability;
- shared payload parity between renderers;
- offline assets, bundled license notices, HTML/script escaping, directed
  edges, lenses, search, and large-graph handling;
- deterministic renderer output where layout state is not intentionally
  dynamic.

Real workspace smoke tests use `md_distribution` and `optasearch` without
hard-coded spec IDs, room names, counts, or artifact kinds. Each smoke performs
workspace refresh, representative query/explain/path/neighbors/impact commands,
both renderer builds, and a second refresh proving current inputs are a no-op.
Browser verification checks both renderers at desktop and mobile sizes for
nonblank output, usable controls, readable details, and non-overlapping UI.

README documentation covers the operational flow:

```text
publish RE/spec/evidence
    -> audit and refresh MemPalace
    -> build or refresh the workspace graph
    -> query, explain, traverse, assess impact, or view
```

## Deferred Opportunities

The following are recorded future directions, not forgotten requirements. They
must be reconsidered only when their trigger is observed; none is needed to
ship useful deterministic graph consumption.

| Opportunity | Why deferred | Revisit when | Architectural attachment |
| --- | --- | --- | --- |
| LLM query interpretation | Adds nondeterminism, cost, and provider policy before lexical retrieval is measured. | Real queries repeatedly fail because intent cannot be expressed through tokens/type filters. | Optional query-planning adapter before `graph_traversal`; deterministic execution remains underneath. |
| Embeddings | Duplicates part of MemPalace's semantic role and needs lifecycle/freshness design. | Evaluation shows lexical plus MemPalace retrieval misses paraphrased graph entities. | Replaceable candidate-source adapter with hashes and model metadata, never canonical node state. |
| Community detection | Inferred grouping has no current delivery authority. | Large workspace graphs cannot be navigated effectively by type, spec, lenses, or query. | Derived renderer/query sidecar keyed by graph hash. |
| Graph database | Persisted JSON is sufficient for current graph size and local workflows. | Measured load or traversal cost exceeds CLI/service budgets, or concurrent remote access is required. | Storage adapter behind `graph_read`, preserving result contracts. |
| MCP exposure | A stable CLI/read API should precede an agent-facing protocol surface. | Command semantics and JSON envelopes prove stable and agent workflows need direct calls. | Thin MCP adapter over the read and traversal services. |
| Code-graph mining | Echelon already has code graph artifacts; merging their semantics requires a separate authority and identity design. | Requirement-to-symbol or change-impact use cases are prioritized. | New audited graph input/composition design, not ad hoc crawling in traversal. |
| PR analysis | Depends on code graph/change-set semantics absent from this slice. | Code graph integration exists and review workflows need requirement impact. | Change-set adapter feeding typed impact traversal. |
| Automatic rebuild hooks | Hidden mutation conflicts with audit-first, explicit recovery behavior. | Operators demonstrate that explicit refresh is a recurring, costly failure point. | Orchestration layer invoking existing audits/refreshes with visible receipts. |
| Interactive editing | Graphs are derived indexes, not authorities. | A concrete workflow identifies the canonical artifact to edit and round-trip validation. | Canonical artifact editor followed by normal mining/audit/build; never direct graph mutation. |

These entries should remain in the design after v1 implementation. If one is
promoted, it receives its own design and removes or updates only its row.

## Implementation Shape

Keep the work focused in these boundaries:

- `echelon.graph_read`: scope resolution, validation, audit-aware loading, and
  node identity resolution;
- `echelon.graph_traversal`: pure query and traversal algorithms;
- `echelon.spec_graph` and its audit: requirement projection and projection
  freshness only;
- `echelon.graph_visualization`: shared payload and existing Cytoscape adapter;
- `echelon.graph_vis_network`: vis-network rendering;
- `echelon.cli_app`: thin command and output adapters.

No unrelated graph schema refactor is required. Shared types may move only when
needed to prevent real duplication between the two renderers or graph scopes.
