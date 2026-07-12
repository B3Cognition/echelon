# Workspace Reverse Engineering Publication Design

## Problem

Reverse-engineering output currently lives under `runs/<run-id>/re/`. That makes
each result discoverable only through the run that produced it. A later feature
run cannot reliably reuse the latest reverse-engineering knowledge, even when the
workspace sources are unchanged.

The existing source-scoped cache design intended to store heavy artifacts under
`.echelon/cache/re/`, then copy them into each run. The storage primitives and
fingerprints exist, but the production workflow does not publish completed RE
results into that cache. Tests seed cache entries directly, so they do not prove
a real first-run/second-run reuse cycle.

OptaSearch demonstrates the failure concretely:

- The workspace contains multiple Git-backed source roots under `sources/`.
- Two completed runs each contain a separate RE directory of approximately 15 MB.
- The workspace has no populated persistent RE cache.
- The completed RE knowledge is not available from a stable workspace path.
- Current broad domain specifications combine evidence from several repositories,
  rather than preserving source ownership and synthesizing cross-source behavior
  separately.

Reverse engineering is workspace knowledge. It must be a first-class workspace
artifact, alongside `sources/`, `specs/`, and `runs/`.

## Goals

- Publish the latest usable RE knowledge under a stable workspace-root `re/`
  directory.
- Map every published source result to a stable workspace source ID.
- Support one source producing many source-owned domain specifications.
- Keep source-owned knowledge separate from cross-source workspace synthesis.
- Refresh only new or changed sources.
- Let later feature runs read published RE directly as brownfield context.
- Keep heavy generated analysis locally persistent without committing it to Git.
- Publish source changes and workspace synthesis as one rollback-capable
  transaction.
- Preserve the last-known-good published generation when refresh fails.
- Automatically publish complete validated results.
- Permit deterministic manual publication of structurally valid partial results.
- Commit changed durable RE documents with normal feature-run artifacts.

## Non-Goals

- This design does not change RE extraction depth or profile defaults.
- This design does not redesign GOLDDIGGER or focused evidence requests.
- This design does not retain committed historical RE snapshots. Git history is
  the history of durable RE documents.
- This design does not make failed or malformed RE output publishable.
- This design does not allow multiple concurrent RE publishers.
- This design does not move implementation source code into `re/`.

## Chosen Architecture

Use one first-class `re/` ownership boundary with three categories:

1. Tracked source-owned and workspace-level knowledge.
2. Ignored fingerprint-addressed heavy artifacts.
3. Ignored staging and lock state used only during publication.

`runs/<run-id>/re/` remains execution evidence and refresh staging for a specific
run. It is not the published source of truth. `.echelon/cache/re/` is removed as
an RE artifact authority.

Feature runs read canonical `re/` paths directly. They do not copy published RE
documents into each run. A generation guard and single-writer publication lock
prevent the published context from changing silently during a feature run.

## Directory Layout

```text
re/
  index.json
  sources/
    <source-id>/
      manifest.json
      overview.md
      specs/
        <domain-id>/
          spec.md
          checklist.md
  workspace/
    manifest.json
    overview.md
    relationships.md
    contracts.md
    domains/
      <domain-id>.md
  .cache/
    .gitignore
    sources/
      <source-id>/
        <fingerprint>/
          cache-manifest.json
          analysis.json
          structure.json
          dependencies.json
          git-history.json
          configs.json
          codegraph-summary.json
          codegraph-analysis.json
  .staging/
    <run-id>/
  .locks/
    publish.lock/
```

Tracked paths:

- `re/index.json`
- `re/sources/**/manifest.json`
- `re/sources/**/overview.md`
- `re/sources/**/specs/**`
- `re/workspace/**`

Ignored paths:

- `re/.cache/**`
- `re/.staging/**`
- `re/.locks/**`

The ignored directories remain under `re/` so reverse engineering has one
filesystem ownership boundary. There is no second hidden RE store under
`.echelon/`.

## Source Identity

`workspace.sources[].id` is the durable identity that joins source code to RE
knowledge:

```text
workspace.sources[id=pressbox-search-api]
  path: sources/pressbox-search-api

re/sources/pressbox-search-api/
```

Rules:

- A configured source ID remains authoritative when its path changes.
- An automatically discovered source uses its directory name as its initial ID.
- Renaming an automatically discovered source without configuring a stable ID is
  treated as removing one source and adding another.
- Duplicate source IDs block planning and publication.
- Publication never guesses that two differently named sources are the same.

## Published Index Contract

`re/index.json` is the canonical RE entry point:

```json
{
  "schema_version": 1,
  "generation": 4,
  "publication_status": "complete",
  "published_at": "2026-07-12T14:30:00Z",
  "published_from_run": "spec-20260712-141500-123456",
  "sources": {
    "pressbox-search": {
      "path": "sources/pressbox-search",
      "published_path": "re/sources/pressbox-search",
      "fingerprint": "sha256:abc123",
      "profile_hash": "sha256:profile123",
      "status": "complete",
      "manifest": "re/sources/pressbox-search/manifest.json"
    },
    "pressbox-search-api": {
      "path": "sources/pressbox-search-api",
      "published_path": "re/sources/pressbox-search-api",
      "fingerprint": "sha256:def456",
      "profile_hash": "sha256:profile123",
      "status": "complete",
      "manifest": "re/sources/pressbox-search-api/manifest.json"
    }
  },
  "workspace": {
    "manifest": "re/workspace/manifest.json",
    "overview": "re/workspace/overview.md",
    "relationships": "re/workspace/relationships.md",
    "contracts": "re/workspace/contracts.md"
  },
  "warnings": []
}
```

`generation` increments only after a publication transaction succeeds. A manual
partial publication sets `publication_status` to `partial` and records warnings.

## Source Manifest Contract

Each `re/sources/<source-id>/manifest.json` records the exact published source
state:

```json
{
  "schema_version": 1,
  "source_id": "pressbox-search-api",
  "source_path": "sources/pressbox-search-api",
  "source_fingerprint": "sha256:def456",
  "git_head": "0123456789abcdef",
  "dirty": false,
  "profile": {
    "profile": "full",
    "depth": "full",
    "max_lines_per_file": 5000,
    "git_history_limit": 2500,
    "codegraph_version": null
  },
  "profile_hash": "sha256:profile123",
  "publication_status": "complete",
  "cache_path": "re/.cache/sources/pressbox-search-api/sha256-def456",
  "overview": "re/sources/pressbox-search-api/overview.md",
  "specs": [
    "re/sources/pressbox-search-api/specs/search-api/spec.md",
    "re/sources/pressbox-search-api/specs/document-indexing/spec.md",
    "re/sources/pressbox-search-api/specs/graphql-contract/spec.md"
  ],
  "warnings": []
}
```

The source manifest is the freshness contract. A source is reusable only when
its current fingerprint and profile hash match the published values and its
required durable files exist.

## Workspace Synthesis Contract

`re/workspace/` contains only knowledge that requires more than one source or
describes the workspace as a whole:

- `overview.md`: workspace purpose, boundaries, and source catalog.
- `relationships.md`: source dependencies and integration topology.
- `contracts.md`: APIs, events, schemas, and other cross-source contracts.
- `domains/*.md`: synthesized domains spanning multiple sources.
- `manifest.json`: exact input source fingerprints and source manifest paths.

Workspace synthesis is regenerated whenever any of these changes:

- A source fingerprint changes.
- A source profile hash changes.
- A source is added or explicitly removed.
- A source publication status changes.

The workspace manifest lists every source input. It cannot claim a generation
that mixes old workspace synthesis with newly published source documents.

## Planning And Freshness

At feature-run initialization, the deterministic planner:

1. Discovers configured workspace sources.
2. Loads `re/index.json` when present.
3. Computes each source fingerprint using source content and effective RE profile.
4. Classifies each source as `current`, `refresh`, `empty`, or `unavailable`.
5. Detects published sources explicitly removed from workspace configuration.
6. Produces a source-scoped execution plan.

Classification rules:

- `current`: source and profile hashes match a structurally valid publication.
- `refresh`: source is new, source hash changed, profile hash changed, or durable
  publication is incomplete.
- `empty`: declared source exists but has no analyzable files.
- `unavailable`: declared source path is temporarily missing.
- `removed`: published source ID was explicitly removed from workspace config.

An unavailable source retains its published knowledge and is surfaced as a run
warning. Temporary filesystem absence never deletes published RE.

## Refresh Flow

For every `refresh` source:

1. Run source-scoped analysis into `runs/<run-id>/re/sources/<source-id>/`.
2. Generate source-owned domain specifications in the same run staging tree.
3. Verify source manifest, fingerprint, profile, analysis, and required specs.
4. Prepare the ignored heavy cache entry under the publication staging tree.
5. Prepare the durable source directory under the publication staging tree.

Unchanged sources are never re-extracted. Their published source manifests and
specs are used as workspace synthesis inputs.

After all selected source refreshes complete, regenerate workspace synthesis from
the union of:

- Current published results for unchanged sources.
- Staged results for refreshed sources.
- Empty manifests for valid empty sources.

## Publication Gate

Automatic publication requires:

- RE run status `complete`.
- Every refreshed source structurally valid.
- Source fingerprints equal the execution plan fingerprints.
- Source profile hashes equal the execution plan profile hashes.
- Required source manifests, overviews, and specs present.
- Workspace manifest references the exact staged/current source inputs.
- Workspace synthesis validation complete.
- No other active feature run in the workspace.

Partial or failed automatic runs never replace published RE.

## Publication Transaction

Publication is deterministic Python/harness behavior, not an agent action.

1. Acquire `re/.locks/publish.lock` with owner run ID, process ID, hostname, and
   acquisition timestamp.
2. Verify there is no other active feature run.
3. Verify the expected current generation still matches `re/index.json`.
4. Build every changed durable and cache path under `re/.staging/<run-id>/`.
5. Validate the complete staged publication.
6. Move current affected paths to rollback backups under staging.
7. Move staged source directories, workspace directory, and cache entries into
   their final locations.
8. Write the new `re/index.json` last, with `generation + 1`.
9. Remove rollback backups and release the lock.

If any replacement fails before step 8, restore every backup and preserve the
old index. If index replacement fails, restore the old generation. A failed
transaction leaves the previously published generation byte-identical.

Readers do not run concurrently with publication. The publication lock plus
active-run check is the supported consistency boundary; rollback protects against
filesystem and process failures.

## Direct Consumption And Generation Guard

Feature runs read `re/` directly. At initialization they record:

```json
{
  "re_generation": 4,
  "re_index": "re/index.json",
  "re_sources": {
    "pressbox-search-api": "re/sources/pressbox-search-api/manifest.json"
  },
  "re_workspace": "re/workspace/manifest.json"
}
```

Before each phase dispatch, the harness verifies that `re/index.json.generation`
still equals the run's `re_generation`. A mismatch blocks the run rather than
silently changing its context.

The run that performs an initial refresh may publish its own staged RE, then pin
the resulting generation before Phase 1 agents consume it. A publisher cannot
run while another feature run is active.

## Manual Partial Publication

The deterministic CLI provides:

```text
echelon re publish <run-id> --allow-partial
echelon re publish <run-id> --allow-partial --commit
```

`--allow-partial` relaxes the quality/completeness threshold only. It does not
relax structural integrity. A partial result must still have:

- Valid source IDs and source mapping.
- Execution-plan fingerprints and profiles.
- Required manifests.
- At least one valid source spec for every non-empty source being published.
- Valid workspace synthesis for the staged source set.

Failed, malformed, or profile-inconsistent output is never publishable.

## Source Lifecycle

### Updated Source

A source pull or local change produces a new fingerprint. Only that source is
refreshed. Workspace synthesis is regenerated and source plus workspace results
publish together.

### Moved Source

When a configured source ID remains stable and its path changes, publication
updates `source_path` under the same `re/sources/<source-id>/` identity.

### Temporarily Missing Source

If a declared source path is unavailable, its published RE remains active. The
run receives an unavailable-source warning. Publication does not remove it.

### Explicitly Removed Source

When a source ID is removed from workspace configuration, its published source
directory is removed from the active RE tree in the same transaction that
regenerates workspace synthesis. Git history retains the deleted durable docs.

### Empty Source

A source with no analyzable files is a successful no-op. Its source manifest has
`publication_status: empty`, no specs are required, and workspace synthesis may
record it as an empty declared source.

A previously populated source that becomes empty must complete a successful
refresh transaction before its old specs are removed.

## Git Behavior

Publication updates the filesystem but does not itself create a Git commit.

Published RE follows normal Git branch semantics. A feature branch sees the RE
generation committed on that branch. After finalization checks out the default
branch, the working tree shows the latest RE generation already merged into the
default branch. A newer feature-branch generation becomes default workspace
context only when that branch is merged.

Echelon does not create a separate RE commit directly on the default branch. If
another feature starts before the first feature branch is merged, it may refresh
the same changed source again. This duplicate work is preferable to silently
mutating the default branch or making unmerged feature knowledge globally
authoritative.

During a normal feature run:

- Phase finalization stages changed tracked `re/` documents with the feature's
  `specs/<spec-id>/` artifacts.
- The normal feature-branch artifact commit includes both.
- Ignored RE cache, staging, and lock paths are never staged.

During standalone RE refresh:

- Published RE changes remain uncommitted by default.
- `--commit` explicitly commits tracked RE changes.

Manual partial publication follows the same rule.

## Lock And Recovery

The publication lock records enough ownership data to diagnose and recover stale
locks. Lock acquisition fails when another live owner exists.

A stale lock may be removed only after confirming:

- The owner process is not alive on the recorded host, or the host differs and
  the lock exceeded the configured stale threshold.
- The owner run is not `running` or `in_progress`.
- Any staged rollback journal is either completed or rolled back.

Lock recovery never deletes the current published generation.

## Validation And Tests

### Publication Tests

- Two-source initial publication creates distinct source manifests/specs and one
  workspace synthesis.
- A second unchanged run dispatches no RE and consumes canonical `re/` paths.
- Updating one source refreshes only that source and workspace synthesis.
- Source and workspace publication increments generation exactly once.
- Failed source refresh leaves every published file and generation unchanged.
- Failed workspace synthesis leaves every published file unchanged.
- Injected filesystem failure during replacement rolls back all affected paths.
- Structurally valid partial override publishes with warnings.
- Failed or malformed override is rejected.

### Source Lifecycle Tests

- Zero-source workspace succeeds without RE dispatch.
- Empty declared source publishes an empty manifest without specs.
- Temporarily missing declared source preserves published knowledge.
- Stable ID with changed path retains published source identity.
- Duplicate source IDs block planning.
- Explicit source removal updates source and workspace state atomically.
- Previously populated source becoming empty removes old specs only after a
  successful publication.

### Concurrency Tests

- Concurrent publisher cannot acquire the publication lock.
- Publisher is rejected while another feature run is active.
- Owning feature run may publish its initial refresh and pin the new generation.
- Generation mismatch blocks phase dispatch.
- Stale lock recovery requires inactive owner and a valid rollback state.

### Git Tests

- Feature finalization stages tracked RE documents.
- Feature finalization never stages `re/.cache`, `re/.staging`, or `re/.locks`.
- Finalization commits RE on the feature branch and checkout of the default branch
  restores that branch's published RE generation.
- Standalone publication does not commit without `--commit`.
- Standalone publication with `--commit` commits only intended tracked RE paths.

### Migration Tests

- Existing completed `runs/<run-id>/re/` output can seed `re/` through
  `echelon re publish` when structurally valid.
- Existing `.echelon/cache/re/` entries, when present, may be imported into
  `re/.cache/` without becoming a second authority.
- An existing feature run without `re/index.json` treats all declared non-empty
  sources as refresh candidates.

## Rollout

1. Introduce the `re/` layout, schemas, validation, publication transaction, and
   direct reader without changing automatic workflow behavior.
2. Add deterministic publication and manual import/publish commands.
3. Add per-source refresh publication and heavy cache writes.
4. Switch feature-run RE context from run-local materialization to canonical
   `re/` paths with generation guards.
5. Enable automatic complete-result publication.
6. Update feature finalization to stage tracked RE documents.
7. Remove `.echelon/cache/re/` as an active authority after migration coverage
   passes.

Each rollout step must preserve the last-known-good published generation and pass
the publication, source lifecycle, concurrency, and Git tests relevant to that
step.

## Resolved Decisions

- `re/` is a first-class workspace directory.
- Durable manifests/specs are tracked; heavy generated data is ignored.
- Only the latest durable result is published; Git provides document history.
- Source-specific and workspace-level knowledge use separate layers.
- Stable configured source IDs are authoritative.
- Complete validated RE publishes automatically.
- Structurally valid partial RE may be published manually.
- Source and workspace synthesis publish as one transaction.
- Feature runs consume canonical `re/` directly.
- Publication is single-writer and generation-guarded.
- Publication does not commit by itself.
- Feature finalization commits changed durable RE documents with feature specs.
- Published RE follows normal branch semantics and becomes default-branch context
  only after merge.
- Standalone publication commits only when explicitly requested.
