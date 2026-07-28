# Spec Artifact Graph Design

**Date:** 2026-07-28
**Status:** Approved for implementation
**Scope:** Spec-scoped deterministic graph for canonical Echelon specs.

## Goal

Add a spec-scoped graph that reconciles specification artifacts, product input
evidence, requirements, tasks, published reverse-engineering (RE), verification
evidence, deferrals, amendments, and audited MemPalace drawers.

The graph is a deterministic, rebuildable index. It must make stale or
ambiguous specification state visible before Echelon adds GraphRAG behavior.

## Core Rules

- Canonical disk artifacts remain the source of truth.
- MemPalace remains a derived semantic index. A drawer may be represented in
  the graph after discovery, but only `reconciliation_status: pass` makes its
  storage edge completeness evidence.
- The graph must not mine requirements or write MemPalace drawers.
- Graph build and audit must reuse existing Echelon parsers, ledgers, and
  audit services instead of reimplementing source extraction.
- The graph is generic over a workspace's discovered artifact metadata, rooms,
  and kinds. It must not hard-code a fixture's rooms, artifact counts, or
  artifact-kind vocabulary.
- Run-local artifacts are excluded by default. The only RE input is the
  published, curated `re/` surface.

## Output

Each canonical spec can have graph artifacts beside the existing spec files:

```text
specs/<id>-<slug>/
  spec-artifact-graph.json
  spec-artifact-graph-audit.json
```

The graph is the machine-readable deterministic index. The audit report
explains whether it is current and coherent. CLI text provides the initial
human view; Markdown renderers are deferred until operators demonstrate a need.

## Node Types

V1 supports:

- `Spec`
- `Requirement`
- `Task`
- `Artifact`
- `MemPalaceDrawer`
- `Amendment`
- `Deferral`

Acceptance criteria are `Requirement` nodes with `category: acceptance`.
Product inputs and verification evidence are `Artifact` nodes with
`role: product-input` or `role: verification-evidence`. V1 does not extract
plan decisions or Lexicon terms as separate nodes.

Minimum node properties are:

| Node | Properties | Authority |
| --- | --- | --- |
| `Spec` | `spec_id`, `path`, `lifecycle` | Canonical spec path and `echelon.artifact_index`. |
| `Requirement` | `requirement_id`, `category`, `source_path` | Canonical `spec.md` parser; category uses the existing ID-prefix mapping. |
| `Task` | `task_id`, `status`, `phase`, `target` | `kernel.task_contract` plus `harness.task_progress`. |
| `Artifact` | `path`, `role`, `hash`, `mining_status` | Existing artifact and mining policy. |
| `MemPalaceDrawer` | Properties defined under Drawer Nodes. | Native planner and audit. |
| `Amendment` | `revision`, `path`, `status` | Canonical amendment directory; status is `promoted`. |
| `Deferral` | `entry_id`, `status`, `selected_ids`, `derived_task_ids`, `reason` | `harness.deferred_scope`. |

Node IDs must be stable and scoped so they can later roll up into a workspace
graph without changing identity:

```text
spec:<spec-id>
req:<spec-id>:<requirement-id>
task:<spec-id>:<task-id>
artifact:<spec-id>:<workspace-relative-path>
drawer:<spec-id>:<drawer-id>
deferral:<spec-id>:<entry-id>
amendment:<spec-id>:<revision>
```

## Edge Types

V1 supports:

- `HAS_REQUIREMENT`
- `DERIVED_FROM`
- `IMPLEMENTS`
- `VERIFIED_BY`
- `STORED_AS`
- `AMENDED_BY`
- `DEFERRED_BY`

Each edge has one deterministic authority:

| Edge | Source | Target | Authority |
| --- | --- | --- | --- |
| `HAS_REQUIREMENT` | `Spec` | `Requirement` | Canonical `spec.md` parser. |
| `DERIVED_FROM` | `Requirement` | product-input `Artifact` | `inputs/traceability.json`; input-unit ID is an edge property. |
| `IMPLEMENTS` | `Task` | `Requirement` | Canonical `tasks.md` `req=` metadata. |
| `VERIFIED_BY` | `Requirement` | verified-ledger `Artifact` | `verified-fulfillment-ledger.json`. |
| `STORED_AS` | `Requirement` or `Artifact` | `MemPalaceDrawer` | Native memory planner plus native audit. |
| `AMENDED_BY` | `Spec` | `Amendment` | Promoted canonical amendment directory. |
| `DEFERRED_BY` | `Requirement` or `Task` | `Deferral` | Active `deferred-scope.json` entry. |

Edges without properties defined in this design use an empty `properties`
object.

Examples:

```text
spec:042 -> HAS_REQUIREMENT -> req:042:FR-001
req:042:FR-001 -> DERIVED_FROM {input_unit_id: input-003} -> artifact:042:inputs/catalog.json
task:042:T-004 -> IMPLEMENTS -> req:042:FR-001
req:042:FR-001 -> STORED_AS {reconciliation_status: pass} -> drawer:042:<deterministic-drawer-id>
req:042:FR-006 -> DEFERRED_BY -> deferral:042:defer-001
req:042:FR-001 -> VERIFIED_BY -> artifact:042:verified-fulfillment-ledger.json
```

## Source Inputs

The graph builder consumes existing canonical artifacts and native source
adapters. Graph entity extraction and MemPalace drawer planning are related,
but not interchangeable authorities:

- Requirement nodes come from the existing canonical spec parser used by the
  native spec-memory planner, restricted to `spec.md` source rows. They never
  come from stored MemPalace search results. The broader
  `harness.canonical_requirements` inventory detects and reconciles requirement
  references in `plan.md`, `coverage-map.md`, and task metadata; those
  references cannot create requirement nodes.
- Task, deferral, amendment, and lifecycle entities come from their existing
  canonical Echelon parsers and ledgers.
- Drawer expectations come only from the native MemPalace planner for the
  artifact's mining domain. The graph never reconstructs drawer IDs itself.
- `spec.md` through the shared canonical requirement extractor; its native
  spec-memory audit supplies canonical-spec and supporting-context drawers.
- `requirements.lexicon.md` through existing Lexicon parsing and validation
  outputs.
- `tasks.md` through the existing task contract parser and task-requirement
  mapping helpers.
- `inputs/manifest.json`, `inputs/catalog.json`, and
  `inputs/traceability.json`.
- `plan.md`, `coverage-map.md`, `quality-gates.md`, and related planning
  artifacts as artifact nodes in v1; structured decision extraction can follow
  after the core graph is stable.
- Published curated `re/` artifacts through the RE snapshot discovery and
  `echelon re memory audit`. RE never reads run-local state or unpublished RE
  worktrees. Because RE is workspace-scoped, a spec graph creates RE artifact
  nodes and records RE audit input only for artifacts named by the selected
  spec's canonical `re-context.json`.
- Curated per-spec verification and fulfillment artifacts through the spec
  evidence snapshot discovery and `echelon spec evidence memory audit <spec>`.
  These include the currently supported evidence allowlist; their rooms and
  kinds are supplied by their metadata, not inferred by the graph.
- `deferred-scope.json` through `harness.deferred_scope`.
- `amendments/<revision>/` through the existing spec amendment model.
- `echelon.artifact_index` for expected artifact presence. `ARTIFACTS.md` is a
  generated navigation artifact, not an authority.

Existing policy-known artifacts are classified as `mined` or
`not-mined-by-policy`. Missing expected artifacts are audit findings, not
nodes. Files outside existing artifact and mining policy are ignored by v1;
the graph does not recursively discover arbitrary workspace files.

If a native parser or audit is unavailable, graph audit reports that exact
domain as unavailable or invalid. It must not guess around malformed
authoritative files.

### Artifact Node Boundary

V1 creates `Artifact` nodes only for:

- existing top-level canonical spec files registered by
  `echelon.artifact_index`;
- existing source artifacts returned by an applicable native MemPalace planner,
  including supported canonical supporting-context artifacts;
- `inputs/manifest.json`, `inputs/catalog.json`, and
  `inputs/traceability.json`;
- curated spec-evidence files returned by native evidence discovery;
- canonical `re-context.json` and its valid named published RE files;
- canonical amendment `change-request.md`, `impact.md`, and amendment
  `inputs/manifest.json`, `inputs/catalog.json`, and
  `inputs/traceability.json`.

Product-input snapshots, arbitrary files beneath canonical directories, and
evidence reference paths do not become v1 nodes. Their identities and hashes
remain properties of their owning control artifact or verification edge.
Planner-returned source artifacts are an explicit bounded exception to
`artifact_index`; the graph does not discover them independently or crawl for
additional files.

Every artifact node has `path`, `role`, `hash`, and `mining_status`. Role is
assigned by existing artifact or evidence policy, or by the native planner
metadata for planner-returned sources; the graph does not infer it.
`mining_status` is `mined` or `not-mined-by-policy`.

### MemPalace Audit Domains

V1 consumes three audit domains, each through its native discovery, planner,
and exact audit implementation:

| Domain | Scope | Audit command | Graph policy |
| --- | --- | --- | --- |
| Canonical spec memory | `spec.md` and supported canonical spec artifacts | `echelon spec memory audit <spec>` | Required for canonical drawer evidence. |
| Published RE memory | Curated, published `re/` artifacts | `echelon re memory audit` | Applicable when canonical `re-context.json` has status `attached` and names at least one artifact. |
| Spec evidence memory | Curated verification/fulfillment artifacts for the selected spec | `echelon spec evidence memory audit <spec>` | Applicable when native evidence snapshot discovery returns at least one artifact. |

An audit report is a graph input in its own right. The graph records its
normalized status, expected and present counts, and SHA-256 digest. Each
`STORED_AS` edge records its drawer's row-level reconciliation result. Only
`reconciliation_status: pass` is completeness proof.

The RE audit is workspace-wide, so the graph hashes only its deterministic
projection for linked RE artifacts: the planned drawer IDs and audit findings
whose drawer IDs match that set. Unrelated RE findings do not stale or fail a
spec graph.

### Drawer Nodes

Native memory planners define the complete expected drawer set for each
applicable domain. V1 creates one `MemPalaceDrawer` node for every expected
planner row with:

- `drawer_id`;
- `source_path`;
- `room`;
- `artifact_kind`;
- expected artifact and content hashes;
- `presence`: `present`, `missing`, `invalid`, or `unavailable`;
- `reconciliation_status`: `pass`, `fail`, or `unavailable`;
- sorted row-level issue codes.

An exact present row with no native audit finding is `pass`. Missing, stale,
wrong-wing, wrong-room, non-canonical, or lifecycle-excluded rows are `fail`.
If the collection cannot be read, all expected rows are `unavailable`.

`STORED_AS` edges are emitted for all expected nodes and repeat `presence` and
`reconciliation_status` for convenient traversal. Unexpected extra or
duplicate drawers remain audit findings and do not become graph nodes.

### Canonical RE Provenance

Normal spec runs already attach an immutable run-local snapshot of the latest
published RE context. During canonical Phase A finalization, Echelon writes a
small provenance artifact beside `spec.md`:

```json
{
  "schema_version": 1,
  "status": "attached",
  "generation": 7,
  "artifacts": [
    {
      "path": "re/workspace/overview.md",
      "hash": "sha256:..."
    }
  ]
}
```

`status` is `attached`, `ignored`, or `absent`. Attached artifact paths are
derived from their path relative to the immutable run snapshot root and must
resolve beneath the published `re/` registry. Hashes are computed from the
snapshot bytes, and rows sort by path. The record contains no copied RE content
and no timestamps.

The graph includes only named RE artifacts whose current published bytes match
the recorded hash. A missing or changed artifact produces an `re_context_stale`
audit finding and no RE provenance or storage edge for that artifact.

For canonical specs created before this artifact exists, RE is not applicable.
Graph audit emits a non-blocking `re_context_unrecorded` warning and creates no
RE nodes or edges.

Requirement-level verification completeness is enforced only when the existing
artifact-index lifecycle is `verified` or `landed`.

### Verification Semantics

V1 reads `verified-fulfillment-ledger.json` through
`harness.verified_fulfillment_ledger.read_verified_ledger`. It emits one
`VERIFIED_BY` edge per ledger row whose requirement exists in current
`spec.md`. The edge targets the ledger `Artifact` node and records:

- `verification_status`;
- `evidence_refs`;
- `verified_commit`;
- `verify_scope`;
- `complete`.

`complete` is true only when the authoritative ledger row status is not
`MISSING`, `PARTIAL`, `DEVIATED`, or `UNVERIFIED`. Unresolved rows still appear
but have `complete: false`. Ledger rows for a requirement absent from current
`spec.md` are audit failures.

Spec-evidence memory health does not alter `complete`. Its freshness and
reconciliation are represented independently by the evidence domain receipt,
`MemPalaceDrawer` nodes, and `STORED_AS` edges. A requirement can therefore
remain verified while its derived evidence memory is stale or unavailable.

The graph does not recompute implementation-input hashes or verifier reuse.
Those remain owned by the existing fulfillment lifecycle. The graph hashes the
canonical ledger as an input and reports whether its current rows provide
requirement-level evidence.

## JSON Contract

`spec-artifact-graph.json` has exactly these top-level fields:

```json
{
  "schema_version": 1,
  "generator_version": "echelon-version",
  "spec_id": "042-normal-mempalace-audit",
  "source_set_digest": "sha256:...",
  "memory_state_digest": "sha256:...",
  "inputs": [],
  "nodes": [],
  "edges": []
}
```

Each node has `id`, `type`, and `properties`. Each edge has `source`, `type`,
`target`, and `properties`.

Nodes sort by `id`; edges sort by `(source, type, target)`; object keys are
serialized with `sort_keys=True`. Duplicate node IDs or duplicate
`(source, type, target)` edges fail graph build. All edge endpoints must
identify existing nodes.

For `STORED_AS`, the source is the matching `Requirement` node for canonical
requirement drawers. Supporting-context, RE, and evidence drawers use their
source `Artifact` node.

`spec-artifact-graph-audit.json` has `schema_version`, `spec_id`, `graph_hash`,
`status`, `findings`, and `recommendations`. Each finding has stable `id`,
`severity`, `code`, `message`, and optional `subject_id`. Findings sort by
`id`. Severity is `warning` or `error`. Finding ID is
`finding:<code>:<subject_id>`, using `graph` when there is no subject; duplicate
code/subject findings are merged. `graph_hash` is the SHA-256 of the exact
graph JSON bytes.

## Input Hashes and Stage Receipts

Every graph build embeds a manifest of the exact artifacts and memory audit
reports used to build the graph. The manifest is also the receipt chain from
canonical sources, through reconciled MemPalace state, to the graph:

```text
canonical source set
    -> successful native MemPalace audits
    -> graph build
```

`source_set_digest` is the SHA-256 of canonical JSON for the sorted current
source records. Each record contains path, role, required/applicable state, and
content hash. The set is produced by the same native discovery and policy used
for a fresh build, not copied from the previous graph. Consequently, adding or
removing an artifact, or changing whether a memory domain is applicable,
changes the digest even when every previously recorded file is unchanged.

Each applicable memory domain contributes a receipt containing its domain-local
`source_set_digest`, normalized audit payload hash, and audit status.
`memory_state_digest` is the SHA-256 of canonical JSON for those sorted receipts.
The receipt is proof only when its audit status is `pass`; matching hashes alone
do not prove that memory refresh or reconciliation succeeded. Receipts are
embedded graph inputs, not additional sidecar files.

V1 proves reconciled state, not command history. It does not record whether an
operator literally ran `refresh`; a passing audit for the current source-set
digest proves that refresh is either unnecessary or completed successfully.

```json
{
  "schema_version": 1,
  "spec_id": "042-normal-mempalace-audit",
  "source_set_digest": "sha256:...",
  "memory_state_digest": "sha256:...",
  "inputs": [
    {
      "path": "specs/042-normal-mempalace-audit/spec.md",
      "hash": "sha256:...",
      "role": "requirements_source",
      "required": true
    },
    {
      "path": "specs/042-normal-mempalace-audit/tasks.md",
      "hash": "sha256:...",
      "role": "task_source",
      "required": true
    },
    {
      "path": "specs/042-normal-mempalace-audit/deferred-scope.json",
      "hash": "sha256:...",
      "role": "deferral_ledger",
      "required": false
    },
    {
      "path": "mempalace://canonical-spec/042-normal-mempalace-audit/audit",
      "hash": "sha256:...",
      "role": "memory_audit_report",
      "required": true,
      "source_set_digest": "sha256:...",
      "status": "pass"
    },
    {
      "path": "mempalace://spec-evidence/042-normal-mempalace-audit/audit",
      "hash": "sha256:...",
      "role": "memory_audit_report",
      "required": false,
      "source_set_digest": "sha256:...",
      "status": "pass"
    },
    {
      "path": "mempalace://published-re/audit",
      "hash": "sha256:...",
      "role": "memory_audit_report",
      "required": false,
      "source_set_digest": "sha256:...",
      "status": "pass"
    }
  ]
}
```

Graph audit first rediscovers the complete current input set and recomputes
`source_set_digest`. It then reruns applicable native MemPalace audits and
recomputes their receipts and `memory_state_digest`. It compares these current
digests with the graph receipts before checking individual inputs for
artifact-specific diagnostics.

The comparisons answer two independent questions:

- MemPalace is current only when each applicable native audit passes for the
  current domain source-set digest.
- The graph is current only when its `source_set_digest` and
  `memory_state_digest` match the current values.

Therefore:

- changed sources plus a failed memory audit mean MemPalace and the graph are
  stale;
- changed sources plus passing memory audits mean MemPalace has been refreshed
  but the graph must be rebuilt;
- unchanged sources plus a changed or failed memory receipt mean MemPalace
  changed or drifted after graph build, so the graph must be rebuilt after
  reconciliation.

Audit payload normalization uses canonical JSON with sorted keys and compact
separators. It includes audit schema, wing, status, artifact/expected/present
counts, and sorted finding/error lists. It excludes labels, filesystem roots,
palace paths, recommendations, and other presentation-only fields.

An input's `required` flag means graph coherence depends on reading that input;
it does not mean every workspace must contain that artifact. `tasks.md` becomes
required at `build`, `verified`, and `landed`; before build, its absence is a
warning. Conditional RE and evidence audit inputs are included only when their
applicability rule is met.

This separates two kinds of staleness:

- MemPalace stale: an applicable native audit does not pass for its current
  domain source-set digest.
- Graph stale: `spec-artifact-graph.json` records a different source-set or
  memory-state digest from the current values.

The graph audit must report both independently. A fresh graph can expose stale
MemPalace. A stale graph cannot be trusted even if MemPalace currently passes.

## Staleness Findings

Graph audit reports stale or unsafe state for:

- `spec.md` changed after graph build.
- `requirements.lexicon.md` changed after graph build.
- `tasks.md` changed after graph build.
- `deferred-scope.json` changed after graph build.
- amendment artifacts changed after graph build.
- the discovered input set or a memory domain's applicability changed after
  graph build.
- an applicable canonical-spec, RE, or spec-evidence audit payload changed
  after graph build.
- MemPalace drawer metadata has stale `artifact_hash`, wrong identity, room,
  wing, lifecycle status, or duplicate/stale extra drawers.
- a curated artifact is present but not reconciled in its applicable memory
  audit.
- task maps to a requirement absent from the current canonical `spec.md`.
- active requirement has no mapped task once lifecycle is `build`, `verified`,
  or `landed`. Before build it is a warning.
- active requirement has no verification evidence when lifecycle is
  `verified` or `landed`.
- deferred requirement has active task work that was not paused by the deferral
  ledger.

Status rules:

- `pass`: no findings.
- `warn`: one or more warning findings and no error findings.
- `fail`: one or more error findings, including stale or malformed graph state.
- `unavailable`: required source services or required artifacts cannot be read.

CLI exit codes are `0` for `pass` and `warn`, `1` for `fail`, and `2` for
`unavailable`.

## Amendments

Spec amendments are first-class graph nodes, not silent edits.

V1 reads only promoted canonical
`specs/<id>/amendments/<revision>/` artifacts. Runtime amendment worktrees are
excluded, just like other run-local state. Each canonical revision produces one
`Amendment` node with revision, path, and status `promoted`. `change-request.md`
and `impact.md` remain hashed `Artifact` nodes; v1 does not parse their prose
into amendment properties.

Each amendment control artifact is a graph input with its own hash. A changed
amendment makes an existing graph stale. After rebuild, the normal current-spec
requirement, task, evidence, and memory checks detect any downstream
inconsistency. There are no amendment-specific coverage rules in v1.

V1 does not reconstruct historical requirement nodes. References to a
requirement absent from current `spec.md` are ordinary audit findings.

Amendment promotion remains owned by `echelon.spec_amendment`, including its
compare-and-swap baseline conflict check. The graph records promoted amendment
artifacts and their hashes but does not repeat promotion validation.

## Deferrals

Deferrals are read from `deferred-scope.json`.

Graph behavior:

- A deferred requirement or task receives a `DEFERRED_BY` edge.
- Deferred active coverage gaps are warnings by default, not failures.
- Restored deferrals with `status: planned` re-enter normal active coverage
  checks.
- Invalid deferral ledger schema or unknown selected IDs are graph audit
  failures.

This prevents a deliberate scope deferral from looking like accidental missing
implementation, while still making the deferred work visible.

## CLI

Add normal lifecycle commands:

```bash
echelon spec graph build <spec-id-or-path> [--write]
echelon spec graph audit <spec-id-or-path> [--json] [--write]
echelon spec graph refresh <spec-id-or-path> [--write]
```

`build` creates an in-memory graph and writes graph artifacts only with
`--write`. It calls the native planner and audit APIs directly; it does not
shell out to memory CLI commands. MemPalace unavailability produces expected
drawer nodes with `presence: unavailable` but does not prevent structural graph
construction. Malformed authoritative disk artifacts still fail build.

`audit` is read-only unless `--write` is set. It validates graph freshness,
source coherence, lifecycle rules, deferrals, amendments, and MemPalace audit
status.

`refresh` runs:

```text
echelon spec graph build <spec> --write
echelon spec graph audit <spec> --write
```

Build and audit each use the applicable native memory audit APIs. `refresh`
does not mine MemPalace. Operators use existing reconciled memory commands for
the relevant domain:

```bash
echelon spec memory refresh <spec> --write
echelon re memory refresh
echelon spec evidence memory refresh <spec>
```

## Error Handling

Errors must be bounded and artifact-specific:

- missing canonical spec: report the selector and expected `specs/` shape;
- malformed graph JSON: report the file and schema version issue;
- changed input set: report added, removed, or applicability-changed identities;
- changed input hash: report old hash, current hash, and path;
- stale MemPalace drawer: report drawer ID and source artifact path, not drawer
  content;
- invalid deferral ledger: report the invalid entry and reason;
- parser unavailable: report the module or service name without a stack trace by
  default.

## Testing

Unit tests:

- graph node IDs are deterministic and spec-scoped;
- graph manifest records hashes for all required inputs;
- source-set digest changes for added, removed, modified, or newly applicable
  inputs;
- memory-state digest changes when a native audit result or domain source set
  changes;
- passing refreshed memory with an older graph reports graph-only staleness;
- audit detects changed `spec.md`, `tasks.md`, `deferred-scope.json`, and a
  changed native canonical-memory audit payload;
- audit distinguishes graph staleness from MemPalace staleness;
- graph records and re-hashes every applicable native audit report, up to
  three;
- each storage edge reflects only its native audit domain's reconciliation
  status;
- every source returned by an applicable native memory planner has an
  `Artifact` node and valid `STORED_AS` endpoints;
- derived artifact references cannot create requirement nodes;
- workspace RE artifacts appear in a spec graph only through canonical
  `re-context.json`;
- legacy specs without `re-context.json` warn without creating RE edges;
- attached RE paths and hashes are normalized from the immutable run snapshot;
- unknown MemPalace rooms and kinds are preserved as drawer metadata without
  becoming implicit mining targets;
- files outside artifact policy are ignored;
- expected missing drawers remain bounded graph nodes while extra drawers
  remain audit findings;
- verified-ledger rows produce resolved or unresolved `VERIFIED_BY` edges
  without reimplementing fulfillment invalidation;
- verified-ledger completeness is unchanged when spec-evidence memory is stale
  or unavailable;
- deferred requirements warn instead of fail by default;
- unknown deferral IDs fail;
- task mappings to requirements absent from current `spec.md` fail;
- active requirements without task mappings warn before build and fail from
  build onward;
- graph JSON rejects duplicate IDs, duplicate edges, and missing endpoints.

CLI tests:

- `echelon spec graph build <id> --write` writes stable graph JSON;
- `echelon spec graph audit <id> --json` emits valid JSON only;
- `echelon spec graph refresh <id> --write` builds and audits without mining
  MemPalace;
- stale input hashes produce exit code 1;
- unavailable required inputs produce exit code 2.

Integration tests:

- build graph for a canonical spec and audit passes;
- edit `spec.md` after graph build and audit reports graph stale;
- edit `spec.md` after memory mining and memory audit reports stale drawers;
- refresh MemPalace after changing `spec.md` without rebuilding the graph and
  verify memory is current while the graph remains stale;
- edit published RE named by `re-context.json` or curated spec evidence after
  memory mining and verify the appropriate stale findings;
- defer a requirement and verify graph audit warns instead of failing the
  missing implementation edge;
- restore the deferral and verify the requirement is checked normally;
- add an amendment that changes requirements and verify derived artifacts must
  refresh before graph audit passes.

## Non-Goals

- Do not introduce a graph database.
- Do not add workspace-wide graph rollup.
- Do not add GraphRAG search, community detection, or graph summaries.
- Do not extract plan decisions or Lexicon terms as graph nodes.
- Do not write graph or audit Markdown.
- Do not mine MemPalace from graph commands.
- Do not auto-delete stale MemPalace drawers.
- Do not use semantic retrieval as proof of graph correctness.
- Do not hand-author graph artifacts with LLM prose.

## Rollout

1. Publish canonical `re-context.json` during normal Phase A finalization.
2. Add graph models, source manifest, stage receipts, and deterministic JSON
   renderer.
3. Add read-only graph audit for existing graph files.
4. Add graph build from canonical spec artifacts.
5. Wire `echelon spec graph build/audit/refresh`.
6. Add hash staleness, deferral, amendment, RE, and MemPalace audit tests.
7. Keep automatic lifecycle integration off until manual reports are stable.
8. Later, allow GraphRAG features to consume the audited graph as discovery
   context, not as correctness proof.
