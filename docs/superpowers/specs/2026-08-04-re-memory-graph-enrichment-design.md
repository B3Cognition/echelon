# RE Memory and Graph Enrichment

## Goal

Make the richer published reverse-engineering outputs useful beyond context-pack rendering. MemPalace must mine source architecture, contracts, components, ADRs, and CodeGraph summaries. Spec and workspace graphs must expose stable RE source topology and structured decisions while retaining prose documents as evidence.

## Design Principles

- Follow the existing hybrid graph model: parse stable structured inputs into semantic nodes; represent prose as typed artifacts.
- Preserve published file paths and content hashes as canonical artifact identity.
- Do not infer component or contract identities from arbitrary Markdown headings.
- Keep graph construction deterministic and useful when MemPalace is unavailable.
- Treat malformed optional CodeGraph or ADR content as artifact evidence, not as a graph-construction failure.

## MemPalace Mining

The curated RE artifact selector will additionally include:

- `re/sources/<source>/architecture.md`
- `re/sources/<source>/contracts.md`
- `re/sources/<source>/components.md`
- `re/sources/<source>/adrs/**/*.md`
- `re/workspace/strategy/adrs/**/*.md`
- `re/sources/<source>/codegraph-summary.json`
- `re/workspace/codegraph-summary.json`

Each snapshot retains the existing reverse-engineering scope and provenance while receiving a specific `artifact_kind` and room:

| Artifact | Kind | Room |
|---|---|---|
| architecture | `re-architecture` | `re-source-architecture` |
| contracts | `re-contracts` | `re-source-contracts` |
| components | `re-components` | `re-source-components` |
| ADR | `re-decision` | `re-source-decisions` |
| workspace ADR | `re-decision` | `re-workspace-decisions` |
| source CodeGraph summary | `re-codegraph-summary` | `re-source-codegraph` |
| workspace CodeGraph summary | `re-codegraph-summary` | `re-workspace-codegraph` |

Existing artifacts keep their current `reverse-engineering` kind and rooms for compatibility. Refresh cleanup will delete all RE-owned kinds, including the new specific kinds, so stale drawers cannot survive a remine.

## Graph Model

For every source represented by artifacts attached through a spec's `re-context.json`, the spec graph creates one stable node:

```text
re-source:<source-id>
```

The node type is `ReverseEngineeringSource` and records the source ID, published manifest path, publication status, and fingerprint when available.

The spec is connected to each source with:

```text
Spec -[USES_RE_SOURCE]-> ReverseEngineeringSource
```

Published RE files remain `Artifact` nodes. Their properties gain `re_artifact_kind` and `re_source_id`. The source node connects to each artifact using a type-specific edge:

- `DESCRIBED_BY` for architecture and overview
- `DECLARES_CONTRACTS_IN` for contracts
- `CATALOGS_COMPONENTS_IN` for components
- `DECIDED_BY` for ADRs
- `SUMMARIZED_BY` for CodeGraph summaries
- `EVIDENCED_BY` for other attached RE files

Each ADR file also creates a stable `Decision` node keyed by source ID plus relative ADR path. The source connects to it with `HAS_DECISION`, and the decision connects to its document with `DOCUMENTED_BY`. ADR title is read from the first Markdown heading when available; no deeper prose parsing is required.

Workspace ADRs create stable `decision:workspace:<relative-path>` nodes. An attached spec connects to each with `INFORMED_BY_DECISION`, and the decision connects to its published document with `DOCUMENTED_BY`.

CodeGraph summaries are structured JSON, but schemas may differ by producer version. This pass models the summary document and source relationship without expanding individual code entities. Entity expansion requires a separately versioned normalization contract.

MemPalace drawer nodes continue to be planned through the existing RE memory adapter. Newly curated artifacts therefore gain `STORED_AS` edges automatically. Missing or unavailable memory remains visible through the existing reconciliation properties.

Workspace graphs inherit and deduplicate `ReverseEngineeringSource`, `Decision`, RE `Artifact`, and drawer nodes from member spec graphs using the existing member-graph composition rules.

## Context and Compatibility

Context-pack selection and rendering do not change. Only artifacts explicitly attached in `re-context.json` enter a spec graph. Published artifacts that are not attached remain mineable in MemPalace but do not become unrelated spec dependencies.

Existing graph consumers continue to see `Artifact` nodes and current fields. New node types, properties, and edges are additive. The source-set digest changes when newly mined artifacts are added or changed, causing graph freshness checks to rebuild as intended.

## Failure Handling

- Missing optional ADR directories or CodeGraph summaries produce no nodes and no error.
- Invalid ADR Markdown still produces a typed artifact; its Decision title falls back to the filename stem.
- Invalid source manifests omit optional source metadata but preserve source identity.
- Invalid attached hashes continue to exclude artifacts under the existing `re-context.json` integrity rule.
- MemPalace unavailability does not suppress source, artifact, or decision topology.

## Tests

1. Curated snapshot selection includes the five new artifact families and excludes raw `codegraph-analysis.json` and cache content.
2. Snapshot metadata assigns the expected specific kinds and rooms.
3. RE memory refresh removes drawers belonging to both legacy and specific RE artifact kinds.
4. A spec graph with attached RE artifacts creates source nodes, typed artifact properties, semantic source edges, and ADR Decision nodes.
5. The same graph contains `STORED_AS` edges for newly mined artifacts when memory is available.
6. CodeGraph summary schema variation does not break graph construction.
7. Workspace graph composition deduplicates shared RE source and decision nodes across member specs.
8. Existing graph and MemPalace tests remain compatible.

## Out of Scope

- Parsing arbitrary architecture, contract, or component Markdown sections into individual semantic entities.
- Expanding every CodeGraph symbol and relationship into the artifact graph.
- Automatically attaching all published RE artifacts to every spec.
