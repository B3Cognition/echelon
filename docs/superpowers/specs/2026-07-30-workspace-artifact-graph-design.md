# Workspace Artifact Graph Design

**Status:** Approved for implementation

**Date:** 2026-07-30

## Goal

Build one deterministic, inspectable workspace graph by preparing and composing
persisted per-spec artifact graphs. The workspace graph provides portfolio
navigation, cross-spec relationships, shared RE and MemPalace identity,
freshness diagnostics, visualization, and a future retrieval input while
orchestrating the existing memory and per-spec graph pipelines rather than
creating replacements for them.

## V1 Boundary

V1:

- discovers canonical specifications directly below `specs/`;
- consumes each persisted `spec-artifact-graph.json`;
- runs the existing live per-spec graph audit before composition;
- refreshes stale canonical memory and per-spec graphs when explicitly asked;
- includes healthy member graphs and visible placeholders for unhealthy ones;
- normalizes genuinely shared artifact and MemPalace drawer identities;
- adds deterministic workspace, target, and supersession relationships;
- writes a replaceable local workspace graph and audit;
- reuses the offline viewer and deterministic DOT export.

V1 does not:

- mine memory or rebuild per-spec graphs from read-only workspace commands;
- read run-local or unpublished RE/evidence artifacts;
- crawl arbitrary workspace files;
- infer semantic similarity or duplicate requirements with an LLM;
- introduce a graph database or GraphRAG retrieval;
- retain historical workspace graph generations.

## Authority And Receipt Chain

Canonical artifacts and their MemPalace projections remain the source
authority. Persisted per-spec graphs remain the only authority for per-spec
nodes and relationships. The workspace graph is a derived local composition:

```text
canonical sources
    -> native MemPalace reconciliation
    -> persisted and audited per-spec graphs
    -> workspace graph composition
```

Composition itself reads exact graph bytes and calls the existing live
per-spec graph audit API. The explicit workspace refresh operation may
orchestrate the existing memory miners, audits, and per-spec graph builder
before composition. It does not implement a second mining or graph-building
path.

## Output

Workspace output is local, replaceable runtime state:

```text
.echelon/runtime/graph/
  workspace-artifact-graph.json
  workspace-artifact-graph-audit.json
  workspace.html
```

The directory is already covered by the workspace contract's
`.echelon/runtime/` ignore rule. Per-spec graph files remain in their canonical
`specs/<id>/` directories.

Writes use a sibling temporary file followed by `os.replace`. A structural
composition failure must leave the previous valid workspace graph untouched.

## Canonical Spec Discovery

Composition inspects direct children of `<workspace>/specs` in lexical order.
A member candidate must:

- be a real directory, not a symlink;
- contain a regular `spec.md`;
- remain inside the canonical `specs/` root.

Run-local `runs/*/specs` trees are never considered. Publication provenance is
recorded when `.echelon-publication.json` is valid, but it is not required for
backward-compatible discovery. The command describes the canonical tree in the
current checkout; operators use the default-branch checkout for a published
workspace view.

No canonical specs is an `unavailable` workspace result and does not replace a
previous workspace graph.

## Member Classification

For each discovered spec, composition:

1. locates `spec-artifact-graph.json`;
2. validates its schema and graph integrity;
3. verifies that its top-level `spec_id` and `spec:<spec-id>` node match the
   discovered canonical directory;
4. computes the SHA-256 of its exact bytes;
5. runs `audit_spec_graph` against current canonical state;
6. hashes canonical JSON from the live audit's `to_dict()` payload;
7. records a member receipt.

Members with live audit status `pass` or `warn` are included. A `warn` member
remains usable and propagates its warnings to the workspace audit.

Members with a missing or malformed graph, or live status `fail` or
`unavailable`, are excluded from detailed composition. The workspace still
contains their `Spec` placeholder with:

```json
{
  "spec_id": "909-example",
  "composition_status": "excluded",
  "member_audit_status": "fail",
  "exclusion_reason": "member_graph_stale"
}
```

This keeps partial workspace inspection useful without presenting stale member
relationships as current.

A member ID mismatch is treated as a malformed member and excluded. Included
`Spec` nodes receive `composition_status: "included"` and their live
`member_audit_status`; excluded placeholders use the same property names so
portfolio rendering does not need a second node contract.

If canonical specs exist but none is usable, composition may write the
placeholder-only graph. Its audit status is `unavailable` and lifecycle
commands return exit code `2`.

## Workspace Graph Schema

`workspace-artifact-graph.json` contains:

```json
{
  "schema_version": 1,
  "generator_version": "3.x",
  "scope": "workspace",
  "workspace_name": "example-workspace",
  "source_set_digest": "sha256:...",
  "member_state_digest": "sha256:...",
  "members": [],
  "inputs": [],
  "nodes": [],
  "edges": []
}
```

`workspace_name` is presentation metadata derived from the workspace directory
name. It is not used as a portable identity. The workspace root node has the
document-local stable ID `workspace:current`.

Each member record contains:

- `spec_id`;
- `graph_path`;
- `graph_hash`, when readable;
- `member_source_set_digest`, when readable;
- `member_memory_state_digest`, when readable;
- `audit_hash`;
- `audit_status`;
- `included`;
- optional `exclusion_reason`.

`source_set_digest` hashes canonical JSON for:

- the sorted canonical spec member set;
- exact persisted member graph paths and hashes;
- a safe `.echelon/config.yml` projection containing only
  `workspace.git_role` and sorted `sources[].id`/`sources[].path`;
- applicable canonical `spec.md` and `targets.yml` hashes used for
  workspace-only relationships.

Missing or invalid canonical workspace config makes workspace discovery
`unavailable`; composition does not fall back to legacy or heuristic source
discovery.

`member_state_digest` hashes sorted member receipts, including live audit hash,
status, inclusion state, and the member's source-set and memory-state digests.

Nodes sort by `id`. Edges sort by `(source, type, target)`. Inputs and members
sort by stable identity. JSON uses `sort_keys=True` and ends with one newline.

## Identity And Merge Rules

Spec-owned identities remain unchanged:

```text
spec:<spec-id>
req:<spec-id>:<requirement-id>
task:<spec-id>:<task-id>
deferral:<spec-id>:<entry-id>
amendment:<spec-id>:<revision-id>
```

Shared identities are normalized during workspace composition:

```text
artifact:<workspace-relative-path>
drawer:<native-mempalace-drawer-id>
source:<configured-source-id>
workspace:current
```

Artifact normalization uses the existing `Artifact.properties.path`; it never
derives identity by parsing the spec-local artifact node ID. Drawer
normalization uses `MemPalaceDrawer.properties.drawer_id`.

Merged nodes receive sorted `member_specs`. Duplicate edges produced after
endpoint normalization are merged and also receive sorted `member_specs`.
Properties other than `member_specs` must be identical.

Two healthy member graphs assigning different properties to one normalized
node or edge is a structural identity conflict. Composition fails, writes no
replacement graph, and reports the conflicting member specs and identity.
Echelon must not select a winner based on discovery order or timestamps.

## Workspace-Owned Nodes And Edges

V1 adds:

| Node or edge | Meaning |
| --- | --- |
| `Workspace` node | The current workspace document root. |
| `SourceRoot` node | A configured source ID and path from canonical workspace config. |
| `CONTAINS_SPEC` | `workspace:current` contains a discovered canonical spec. |
| `TARGETS` | A spec targets a configured source root. |
| `SUPERSEDES` | A spec frontmatter declaration supersedes another discovered spec. |

Workspace-only relationships use existing canonical config, frontmatter, and
target parsers. They do not reparse requirements, tasks, evidence, RE content,
or MemPalace drawers.

`TARGETS` is emitted only when the target resolves to a configured source ID.
Unresolved target declarations remain visible on the `Spec` node and produce a
warning rather than an invented source node.

`SUPERSEDES` is emitted only when the named target spec is discovered.
References to an absent spec produce a warning and no placeholder historical
spec.

Existing member edges such as `HAS_REQUIREMENT`, `DERIVED_FROM`, `IMPLEMENTS`,
`VERIFIED_BY`, `STORED_AS`, and `DEFERRED_BY` are preserved after endpoint
normalization. Shared RE artifacts and drawers therefore become natural
cross-spec connection points.

## Workspace Audit

`workspace-artifact-graph-audit.json` contains:

- `schema_version`;
- `scope: "workspace"`;
- `workspace_name`;
- `graph_hash`;
- `status`;
- sorted member summaries;
- sorted findings;
- recommendations.

Each finding has stable `id`, `severity`, `code`, `message`, and optional
`subject_id`. Subject IDs use the graph identity involved, normally
`spec:<spec-id>` for member problems.

Audit rediscovers specs, rereads exact member graph bytes, reruns live member
audits, and recomputes workspace-only inputs. It reports:

- `workspace_graph_missing` or invalid workspace graph schema;
- canonical spec added or removed after composition;
- member graph added, removed, or changed;
- member graph currently stale or unavailable;
- member audit or MemPalace receipt changed after composition;
- workspace config, target, or supersession input changed;
- unresolved target or missing superseded spec;
- normalized node or edge identity conflict;
- stored graph source-set or member-state digest mismatch.

The persisted per-spec audit sidecar is not an authority and is not required.
Workspace audit always uses the live per-spec audit result.

Status rules:

- `pass`: every member is included and no findings exist;
- `warn`: all members are usable and only warnings exist;
- `fail`: at least one member is missing, stale, malformed, or excluded, or
  another error finding exists;
- `unavailable`: canonical workspace discovery cannot run, no canonical specs
  exist, or canonical specs exist but none has a usable graph.

Exit codes remain `0` for `pass` and `warn`, `1` for `fail`, and `2` for
`unavailable`.

## CLI

Add a `workspace` subcommand beneath the existing top-level graph capability:

```bash
echelon graph workspace build [--write]
echelon graph workspace audit [--json] [--write]
echelon graph workspace refresh [--write]
echelon graph workspace view [--lens <lens>] [--output <path>] [--no-open]
echelon graph workspace export [--format dot] [--lens <lens>] [--output <path>]
```

`build` composes an in-memory graph and writes only with `--write`. Successful
serialization returns `0` even when members were excluded; health belongs to
the audit result.

`audit` is read-only unless `--write` is supplied.

`refresh` composes and audits the newly composed in-memory candidate. Without
`--write`, it is a dry preview and does not audit an older persisted workspace
graph or mutate upstream state. With `--write`, it:

1. audits shared RE memory once and refreshes it only when stale;
2. audits each spec's requirement and evidence memory and refreshes only stale
   applicable domains;
3. audits each per-spec graph and rebuilds only missing, invalid, or
   source/input/memory-stale graphs; coherence failures such as missing
   verification or task mappings remain visible but are not rewritten;
4. composes the exact persisted member graph bytes;
5. atomically replaces the workspace graph and writes its audit.

One member's refresh failure does not prevent repair of other members. The
failed member remains visible as an excluded placeholder and the command
returns the final workspace audit status.

`view` and `export` consume the persisted workspace graph and run a live
workspace audit. They produce output even for `fail`, then return the audit exit
code. A valid placeholder-only graph with audit status `unavailable` is still
rendered or exported and then returns `2`. A missing or structurally invalid
persisted workspace graph produces no output and returns `2`.

No compatibility alias or alternate command hierarchy is added.

## Visualization

The workspace viewer reuses the offline Cytoscape bundle, node details, search,
neighborhood controls, audit findings, and existing lenses:

- `exceptions`;
- `traceability`;
- `memory`;
- `delivery`;
- `all`.

It adds a workspace-only `portfolio` lens containing:

- workspace root;
- spec nodes;
- configured source roots;
- `CONTAINS_SPEC`, `TARGETS`, and `SUPERSEDES` edges.

The default is `exceptions` when the workspace audit has findings and
`portfolio` otherwise.

Workspace graphs may be much larger than one spec graph. The HTML payload
embeds nodes and edges once and filters lenses client-side; it must not embed a
complete duplicate element list per lens. Dense labels remain hidden at fitted
overview zoom and appear through zoom, selection, and search.

V1 does not add a second visualization application, server, graph database, or
workspace-specific layout engine.

## Failure And Recovery

Normal recovery is one explicit workspace operation:

```text
memory, member graph, or workspace graph stale
    -> echelon graph workspace refresh --write
```

The refresh command audits before mutation, avoids re-mining current domains
and rewriting current member graphs, and uses existing hash-based adoption and
reconciliation protections. `build`, `audit`, `view`, and `export` remain
read-only with respect to memory and per-spec graphs. Audit findings identify
the affected spec and stale layer when bounded repair cannot complete.

## Implementation Shape

Keep responsibilities separated:

- `echelon.workspace_graph`: discovery, receipts, normalization, composition,
  deterministic rendering, and atomic writes;
- `echelon.workspace_graph_audit`: live member and workspace freshness audit;
- `echelon.workspace_graph_refresh`: audit-first orchestration of existing
  memory refresh and per-spec graph APIs, with per-domain/member outcomes;
- `echelon.graph_visualization`: scope-neutral rendering plus workspace
  `portfolio` lens and single-payload client-side filtering;
- `echelon.cli_app`: the `echelon graph workspace` command adapter.

Shared graph dataclasses and validation may move from `spec_graph` into a small
scope-neutral module only if doing so removes real duplication. The per-spec
JSON schema and command behavior must remain unchanged.

## Verification

Focused verification must cover:

- deterministic output independent of directory enumeration order;
- healthy multi-spec composition;
- shared RE artifact and drawer normalization;
- duplicate edge provenance merging;
- structural identity conflicts preserving the previous graph;
- missing, malformed, stale, warn, and unavailable member behavior;
- added and removed spec freshness;
- changed member graph and changed member audit receipts;
- target and supersession edges and warnings;
- no upstream mutation from `build`, `audit`, `view`, or `export`;
- refresh audits first, refreshes shared RE once, and skips current domains;
- refresh isolates member failures and reports unrepaired layers;
- atomic writes;
- workspace CLI output and exit codes;
- viewer behavior with a multi-spec graph;
- real-workspace smoke tests on `md_distribution` and `optasearch`.

## Deferred Follow-Ups

After v1 proves useful, the workspace graph can support:

- bounded retrieval and context selection;
- semantic cross-spec relationship proposals with evidence and human approval;
- product-input entity identity across specs;
- historical snapshots or graph diffs;
- external graph-tool adapters;
- a graph database only if measured scale or query requirements justify one.
