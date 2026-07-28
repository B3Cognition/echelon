# Spec Artifact Graph Design

**Date:** 2026-07-28
**Status:** Draft for review
**Scope:** Spec-scoped deterministic graph for canonical Echelon specs.

## Goal

Add a spec-scoped graph that reconciles specification artifacts, product input
evidence, requirements, tasks, verification evidence, deferrals, amendments,
and audited MemPalace drawers.

The graph is a deterministic, rebuildable index. It must make stale or
ambiguous specification state visible before Echelon adds GraphRAG behavior.

## Core Rules

- Canonical disk artifacts remain the source of truth.
- MemPalace remains a derived semantic index and must pass exact audit before
  its drawers count as usable graph evidence.
- The graph must not mine requirements or write MemPalace drawers.
- Graph build and audit must reuse existing Echelon parsers, ledgers, and
  audit services instead of reimplementing source extraction.
- Run-local artifacts are excluded by default; v1 reads canonical
  `specs/<id>-<slug>/` only.

## Output

Each canonical spec can have graph artifacts beside the existing spec files:

```text
specs/<id>-<slug>/
  spec-artifact-graph.json
  spec-artifact-graph.md
  spec-artifact-graph-audit.json
  spec-artifact-graph-audit.md
```

The JSON graph is machine-readable. The Markdown graph is a human navigation
view. The audit reports explain whether the graph is current and coherent.

## Node Types

V1 supports:

- `Spec`
- `ProductInput`
- `Requirement`
- `AcceptanceCriterion`
- `LexiconTerm`
- `PlanDecision`
- `Task`
- `Artifact`
- `VerificationEvidence`
- `MemPalaceDrawer`
- `Amendment`
- `Deferral`
- `Warning`

Node IDs must be stable and scoped so they can later roll up into a workspace
graph without changing identity:

```text
spec:<spec-id>
req:<spec-id>:<requirement-id>
task:<spec-id>:<task-id>
artifact:<spec-id>:<relative-path>
drawer:<spec-id>:<drawer-id>
deferral:<spec-id>:<entry-id>
amendment:<spec-id>:<revision>
warning:<spec-id>:<finding-id>
```

## Edge Types

V1 supports:

- `HAS_REQUIREMENT`
- `DERIVED_FROM`
- `REPRESENTED_IN`
- `PLANNED_BY`
- `IMPLEMENTS`
- `MODIFIES`
- `VERIFIED_BY`
- `STORED_AS`
- `AMENDED_BY`
- `SUPERSEDES`
- `DEFERRED_BY`
- `PAUSES`
- `FLAGS`

Example edges:

```text
spec:042 -> HAS_REQUIREMENT -> req:042:FR-001
req:042:FR-001 -> DERIVED_FROM -> input:042:inputs/manifest.json#input-003
req:042:FR-001 -> PLANNED_BY -> task:042:T-004
task:042:T-004 -> IMPLEMENTS -> req:042:FR-001
req:042:FR-001 -> STORED_AS -> drawer:042:<deterministic-drawer-id>
req:042:FR-006 -> DEFERRED_BY -> deferral:042:defer-001
warning:042:stale-memory -> FLAGS -> drawer:042:<deterministic-drawer-id>
```

## Source Inputs

The graph builder consumes existing canonical artifacts and services:

- `spec.md` through the shared canonical requirement extractor and MemPalace
  requirement planner where drawer identity is needed.
- `requirements.lexicon.md` through existing Lexicon parsing and validation
  outputs.
- `tasks.md` through the existing task contract parser and task-requirement
  mapping helpers.
- `inputs/` product input manifests, snapshots, and traceability ledgers.
- `plan.md`, `coverage-map.md`, `quality-gates.md`, and related planning
  artifacts as artifact nodes in v1; structured decision extraction can follow
  after the core graph is stable.
- `traceability-matrix.md`, `verification-summary.md`,
  `fulfillment-report.md`, and `gap-report.md` as verification evidence.
- `deferred-scope.json` through `harness.deferred_scope`.
- `amendments/<revision>/` through the existing spec amendment model.
- `mempalace-audit.json` or a live `echelon.mempalace_audit` result for drawer
  nodes and storage findings.
- `ARTIFACTS.md` and `echelon.artifact_index` for expected artifact presence.

If a source parser is unavailable or a source artifact is malformed, graph
audit reports the specific source as unavailable or invalid. It must not guess
around malformed authoritative files.

## Input Hash Manifest

Every graph build writes a manifest of the exact artifacts and reports used to
build the graph:

```json
{
  "schema_version": 1,
  "spec_id": "042-normal-mempalace-audit",
  "generated_at": "2026-07-28T00:00:00Z",
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
      "path": "specs/042-normal-mempalace-audit/mempalace-audit.json",
      "hash": "sha256:...",
      "role": "memory_audit",
      "required": false
    }
  ]
}
```

Graph audit recomputes these hashes from disk. If any recorded input changed,
the graph is stale.

This separates two kinds of staleness:

- MemPalace stale: a drawer's stored `artifact_hash` no longer matches the
  canonical artifact on disk.
- Graph stale: `spec-artifact-graph.json` was built from older input hashes.

The graph audit must report both independently. A fresh graph can expose stale
MemPalace. A stale graph cannot be trusted even if MemPalace currently passes.

## Staleness Findings

Graph audit reports stale or unsafe state for:

- `spec.md` changed after graph build.
- `requirements.lexicon.md` changed after graph build.
- `tasks.md` changed after graph build.
- `deferred-scope.json` changed after graph build.
- amendment artifacts changed after graph build.
- `mempalace-audit.json` changed after graph build.
- MemPalace drawer metadata has stale `artifact_hash`.
- task maps to an unknown, removed, superseded, or deferred requirement.
- active requirement has no mapped task.
- active requirement has no verification evidence after the verified lifecycle
  stage.
- deferred requirement has active task work that was not paused by the deferral
  ledger.
- verification evidence references a missing artifact.

Status rules:

- `pass`: graph inputs are current and active nodes are coherent.
- `warn`: graph is usable but has deferrals, duplicate inactive memory,
  optional missing artifacts, retrieval probe warnings, or non-blocking cleanup
  recommendations.
- `fail`: graph is stale, malformed, missing required active coverage, or
  contradicts canonical lifecycle state.
- `unavailable`: required source services or required artifacts cannot be read.

## Amendments

Spec amendments are first-class graph nodes, not silent edits.

The graph reads amendment metadata from existing amendment worktree state and
canonical `specs/<id>/amendments/<revision>/` artifacts when present. Each
amendment node records:

- amendment ID and revision;
- baseline branch and commit;
- amended commit when known;
- description;
- product input count;
- status.

If an amendment changes `spec.md`, graph audit warns or fails until derived
artifacts are rebuilt:

- `requirements.lexicon.md` must reflect current requirements.
- `tasks.md` must map current active requirements.
- `mempalace-audit.json` must reflect current canonical drawer expectations.
- `traceability-matrix.md` and verification artifacts must not claim removed
  or superseded requirements as active.

Removed requirements remain in the graph with lifecycle status `removed` or
`superseded` when that status can be proven. They are not silently deleted from
the graph history.

An amendment baseline conflict is a graph audit failure because it means the
canonical branch changed independently of the amendment baseline.

## Deferrals

Deferrals are read from `deferred-scope.json`.

Graph behavior:

- A deferred requirement or task receives a `DEFERRED_BY` edge.
- A deferral receives `PAUSES` edges to derived tasks.
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
echelon spec graph audit <spec-id-or-path> [--json] [--write] [--strict]
echelon spec graph refresh <spec-id-or-path> [--write]
```

`build` creates an in-memory graph and writes graph artifacts only with
`--write`.

`audit` is read-only unless `--write` is set. It validates graph freshness,
source coherence, lifecycle rules, deferrals, amendments, and MemPalace audit
status.

`refresh` runs:

```text
echelon spec memory audit <spec>
echelon spec graph build <spec> --write
echelon spec graph audit <spec> --write
```

It does not mine MemPalace. Operators use existing memory commands for that:

```bash
echelon spec memory refresh <spec> --write
```

## Error Handling

Errors must be bounded and artifact-specific:

- missing canonical spec: report the selector and expected `specs/` shape;
- malformed graph JSON: report the file and schema version issue;
- changed input hash: report old hash, current hash, and path;
- stale MemPalace drawer: report drawer ID and source artifact path, not drawer
  content;
- invalid deferral ledger: report the invalid entry and reason;
- amendment conflict: report baseline and current commit;
- parser unavailable: report the module or service name without a stack trace by
  default.

## Testing

Unit tests:

- graph node IDs are deterministic and spec-scoped;
- graph manifest records hashes for all required inputs;
- audit detects changed `spec.md`, `tasks.md`, `deferred-scope.json`, and
  `mempalace-audit.json`;
- audit distinguishes graph staleness from MemPalace staleness;
- deferred requirements warn instead of fail by default;
- strict mode can fail deferred active coverage gaps;
- unknown deferral IDs fail;
- task mappings to removed or superseded requirements fail;
- active requirements without task mappings fail;
- amendment baseline conflicts fail.

CLI tests:

- `echelon spec graph build <id> --write` writes stable JSON and Markdown;
- `echelon spec graph audit <id> --json` emits valid JSON only;
- `echelon spec graph refresh <id> --write` runs memory audit before graph
  build;
- stale input hashes produce exit code 1;
- unavailable required inputs produce exit code 2.

Integration tests:

- build graph for a canonical spec and audit passes;
- edit `spec.md` after graph build and audit reports graph stale;
- edit `spec.md` after memory mining and memory audit reports stale drawers;
- defer a requirement and verify graph audit warns instead of failing the
  missing implementation edge;
- restore the deferral and verify the requirement is checked normally;
- add an amendment that changes requirements and verify derived artifacts must
  refresh before graph audit passes.

## Non-Goals

- Do not introduce a graph database.
- Do not add workspace-wide graph rollup.
- Do not add GraphRAG search, community detection, or graph summaries.
- Do not mine MemPalace from graph commands.
- Do not auto-delete stale MemPalace drawers.
- Do not use semantic retrieval as proof of graph correctness.
- Do not hand-author graph artifacts with LLM prose.

## Rollout

1. Add graph models, source manifest, and JSON/Markdown renderers.
2. Add read-only graph audit for existing graph files.
3. Add graph build from canonical spec artifacts.
4. Wire `echelon spec graph build/audit/refresh`.
5. Add hash staleness, deferral, amendment, and MemPalace audit tests.
6. Keep automatic lifecycle integration off until manual reports are stable.
7. Later, allow GraphRAG features to consume the audited graph as discovery
   context, not as correctness proof.
