# EGR-123 Source-Scoped RE Cache Design

## Problem

`echelon spec run` currently treats source presence as a run-wide brownfield
signal. When a workspace starts with several existing repositories, uses full
reverse engineering as design input, then adds a new Echelon-built target repo,
the next Phase A run detects all repositories as brownfield again.

That creates three failures:

- Full reverse engineering runs across unchanged sources, burning unnecessary
  LLM and CodeGraph budget.
- New Echelon-built target repositories are treated the same as original legacy
  context repositories.
- RE specification output can consume canonical `specs/NNN-*` numbering during
  ordinary feature runs.

The desired behavior is source-scoped freshness: unchanged source context is
reused, changed or new source context is refreshed, and the current feature run
receives a normal run-local RE artifact view.

## Goals

- Make Phase A reverse engineering target-aware and source-fingerprint-aware.
- Preserve the existing run-local artifact contract consumed by SCOUT, MODELER,
  stack detection, and RE agents.
- Avoid full workspace RE unless explicitly requested.
- Prevent ordinary feature runs from publishing RE docs into the canonical
  product spec namespace.
- Keep standalone explicit RE workflows able to publish `specs/000-re-overview`
  and `specs/NNN-re-*`.

## Non-Goals

- Do not redesign the RE extraction pipeline itself.
- Do not require SCOUT, MODELER, or stack detection to read persistent cache
  paths directly.
- Do not remove current full-refresh behavior; keep it behind an explicit
  policy.
- Do not infer user intent from timestamps or directory age.

## Architecture

Add a deterministic RE planning layer before GOLDDIGGER Mode 1 dispatch.

The planner discovers workspace sources, resolves the selected RE policy, computes
each source fingerprint, and writes a run-local execution plan:

```json
{
  "policy": "target-changed",
  "target_source": "prosaic",
  "sources": [
    {"id": "original-a", "action": "reuse", "fingerprint": "..."},
    {"id": "original-b", "action": "reuse", "fingerprint": "..."},
    {"id": "original-c", "action": "reuse", "fingerprint": "..."},
    {"id": "prosaic", "action": "refresh", "fingerprint": "..."}
  ]
}
```

Persistent cache stores per-source extraction artifacts. Each Phase A run then
materializes a compatibility view under `runs/<run-id>/re/` using cached and
refreshed source artifacts.

```text
.echelon/cache/re/
  sources/<source-id>/<fingerprint>/
    manifest.json
    analysis.json
    structure.json
    dependencies.json
    git-history.json
    configs.json
    codegraph-summary.json
    codegraph-analysis.json
    re-context.md

runs/<run-id>/re/
  workspace-manifest.json
  re-execution-plan.json
  re-source-index.json
  analysis.json
  cross-repo.json
  original-a/analysis.json
  original-b/analysis.json
  original-c/analysis.json
  prosaic/analysis.json
```

The run-local view remains the public contract. `state.json.golddigger_artifacts`
points at run-local paths, not cache paths.

## RE Policies

Add Phase A CLI options:

```bash
echelon spec run --target prosaic --re-policy target-changed "..."
echelon spec run --re-policy changed "..."
echelon spec run --re-policy refresh-all "..."
```

Policies:

- `none`: no RE artifacts.
- `cached-only`: use existing cache only; never invoke RE.
- `changed`: refresh new or changed sources and reuse unchanged sources.
- `target-changed`: refresh the target if new or changed; reuse cached non-target
  context.
- `target-only`: include and refresh only the selected target source.
- `refresh-all`: current expensive full workspace RE behavior.

Defaults:

- No `--target`: `changed`.
- With `--target`: `target-changed`.

## Fingerprints

Fingerprinting is deterministic and source-local:

- Clean Git source: use the source repository HEAD commit plus relevant RE
  profile inputs.
- Dirty Git source: combine HEAD, tracked/untracked relevant file hashes, and RE
  profile inputs; mark `dirty: true`.
- Non-Git source: hash relevant source/config files and RE profile inputs.

The cache key must include RE profile inputs such as profile, depth,
`max-lines-per-file`, git history limit, and CodeGraph availability/version where
that affects output shape.

## Artifact Contract

`re-source-index.json` records cache provenance:

```json
{
  "schema_version": 1,
  "policy": "target-changed",
  "target_source": "prosaic",
  "sources": [
    {
      "id": "original-a",
      "path": "sources/original-a",
      "fingerprint": "...",
      "action": "reuse",
      "dirty": false,
      "cache_path": ".echelon/cache/re/sources/original-a/...",
      "run_path": "runs/<run-id>/re/original-a"
    }
  ]
}
```

`golddigger_artifacts` should continue to expose run-local paths:

```yaml
golddigger_artifacts:
  manifest: runs/<run-id>/re/workspace-manifest.json
  source_index: runs/<run-id>/re/re-source-index.json
  analysis: runs/<run-id>/re/analysis.json
  cross_repo: runs/<run-id>/re/cross-repo.json
  per_repo:
    - runs/<run-id>/re/original-a/
    - runs/<run-id>/re/prosaic/
  re_contexts:
    - runs/<run-id>/re/original-a/re-context.md
    - runs/<run-id>/re/prosaic/re-context.md
```

SCOUT and MODELER keep using `golddigger_artifacts` and run-local RE files. They
do not depend on cache internals.

## Spec Namespace Rule

Ordinary `echelon spec run` must not publish RE documentation into canonical
product spec folders:

- No `specs/NNN-re-*` creation during feature Phase A.
- No canonical `specs/000-re-overview` mutation during feature Phase A.
- RE context for feature runs is surfaced through `golddigger_artifacts` as
  `runs/<run-id>/re/` paths; persistent copies may live in cache internally.

Standalone explicit RE workflows may still publish canonical RE spec folders
because their goal is reverse-engineering documentation.

## Workflow Changes

- `echelon spec run` parses `--target` and `--re-policy`.
- `SquadStateStore.initialize()` persists target and policy fields.
- Phase 1 pre-dispatch runs the RE planner/materializer before GOLDDIGGER.
- GOLDDIGGER Mode 1 dispatch is conditioned on planned refresh work, not only
  `mode = brownfield`.
- When all selected artifacts are cache hits, GOLDDIGGER is skipped and state is
  populated with materialized run-local artifacts.
- When any source needs refresh, GOLDDIGGER receives the source-scoped refresh
  plan and writes refreshed artifacts to cache before run-local materialization.

## Components

- `src/harness/re_fingerprint.py`: source fingerprint computation.
- `src/harness/re_cache.py`: cache path resolution, cache hit validation, and
  atomic cache writes.
- `src/harness/re_planner.py`: policy resolution and execution-plan generation.
- `src/harness/re_materializer.py`: assemble `runs/<run-id>/re/` from cache and
  refreshed outputs.
- `src/echelon/cli.py`: Phase A `--target` and `--re-policy` parsing.
- `src/harness/squad.py`: persist policy/target and refresh run context.
- `src/harness/squad_executors.py`: pre-dispatch planning/materialization and
  source-scoped GOLDDIGGER routing.
- `extension/agents/exploration/golddigger.md`: accept source-scoped refresh
  plans and stop requiring canonical RE spec output for ordinary feature runs.
- RE docs: document persistent cache versus run-local compatibility artifacts.

## Testing

- Planner test: three unchanged cached sources plus one new source produces three
  `reuse` actions and one `refresh` action.
- Materializer test: run-local `analysis.json`, per-source directories, and
  `re-source-index.json` are produced from cache hits.
- CLI test: `--target` defaults policy to `target-changed`; no target defaults to
  `changed`; explicit policy is honored.
- Executor test: cache-only plan skips GOLDDIGGER and still populates
  `golddigger_artifacts`.
- Executor test: refresh plan dispatches GOLDDIGGER only for refresh sources.
- Contract test: ordinary `echelon spec run` does not create canonical
  `specs/NNN-re-*`.
- Compatibility test: SCOUT prompt still receives run-local artifact paths.
- Policy test: `refresh-all` preserves current full workspace behavior.
- Dirty source test: dirty fingerprints are deterministic and marked in
  `re-source-index.json`.

## Rollout

Implement in slices:

1. Add fingerprints, cache model, planner, and materializer with tests.
2. Wire CLI/state policy fields without changing default runtime behavior.
3. Enable cache-hit materialization and GOLDDIGGER skip.
4. Add source-scoped refresh dispatch.
5. Move ordinary feature-run RE docs out of canonical `specs/NNN-re-*`.
6. Update docs, changelog, and EGR register.

## Resolved Decisions And Remaining Question

- Materialization copies cache artifacts into `runs/<run-id>/re/` instead of
  symlinking them. Runs must be self-contained so they can be archived after work
  is done.
- `cross-repo.json` is recomputed cheaply during materialization from the
  selected per-source metadata. It is not cached by workspace fingerprint in the
  first implementation because its contents depend on the selected source set.
- Remaining question: when `--re-policy target-only` excludes sibling source
  context, should prompts still list excluded sibling source IDs as forbidden
  roots for containment? This would not expose their RE content; it would only
  tell agents which workspace siblings they must not inspect.
