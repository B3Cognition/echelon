# Echelon Human Wiki Design

**Date:** 2026-07-18

**Status:** Approved

**Scope:** Workspace-scoped, generated navigation for Echelon Markdown artifacts

## Summary

Echelon will generate a local, read-only Markdown wiki that helps people navigate
the artifacts already published under `specs/` and `re/`. The wiki is a disposable
projection, not a new source of truth, agent memory system, or editing surface.

The initial implementation will be deterministic, offline, and workspace-scoped.
It will require neither an LLM nor Obsidian. The generated directory will be a
self-contained Markdown vault that works in ordinary Markdown viewers and includes
lightweight Obsidian configuration for users who choose to open it in Obsidian.

## Problem

Echelon produces a rich artifact set across specification, reverse engineering,
planning, delivery, and verification. Individual spec directories already have a
deterministic `ARTIFACTS.md`, but people still need to discover the workspace-wide
structure, determine what work is active, find the correct reading order, and
follow relationships between sources, domains, specs, requirements, tasks, risks,
and verification evidence.

Agent retrieval is already handled elsewhere in Echelon. This feature is solely
for human orientation and navigation.

## Goals

- Give every workspace one obvious human entry point.
- Make lifecycle state, artifact completeness, freshness, and warnings visible.
- Provide ordered reading paths for each spec.
- Connect specs and reverse-engineering artifacts using explicit evidence.
- Work without a server, network connection, LLM invocation, or required viewer.
- Preserve existing artifact ownership and publication contracts.
- Regenerate cheaply and safely after cloning or changing a workspace.
- Keep the design open to future renderers without coupling discovery to Markdown.

## Non-goals

The first version will not provide:

- Cross-workspace aggregation.
- A replacement for MemPalace or other agent retrieval paths.
- Static HTML output.
- Built-in full-text, vector, or semantic search.
- Editing or synchronization back to canonical artifacts.
- A committed generated wiki.
- One page per requirement or task.
- Relationships inferred from textual similarity.
- A background filesystem watcher.
- Installation of Obsidian or an external `llm-wiki` package.

## Design principles

### Canonical artifacts remain authoritative

Tracked artifacts under `specs/` and published reverse-engineering artifacts under
`re/` remain the source of truth. Users edit those files through the existing
Echelon workflows. The generated wiki is read-only and may be deleted and rebuilt
at any time.

### Adopt the LLM-wiki pattern, not a package

Andrej Karpathy's LLM-wiki document describes an abstract pattern rather than a
specific implementation. Echelon adopts its useful separation between sources,
generated wiki content, and schema, but does not install a third-party product.
Echelon also differs deliberately by compiling navigation deterministically: its
source artifacts have already been synthesized by Echelon agents, and the target
problem is human navigation rather than new knowledge synthesis.

Reference: <https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>

### Obsidian is an optional viewer

The output uses interoperable Markdown links. The generated directory includes a
minimal `.obsidian/` configuration using core features only, but generation and
reading do not depend on Obsidian. Echelon does not install Obsidian. After a build,
the CLI recommends it briefly as an optional viewer for backlinks and graph
navigation.

### Evidence before inference

The wiki creates relationships only from paths, manifests, frontmatter, stable
identifiers, targets, traceability artifacts, and other deterministic evidence.
It does not guess relationships from prose or similarity. Missing relationships
remain visibly unavailable.

## Configuration contract

The generator consumes Echelon's fully resolved configuration cascade rather than
reading `.echelon/config.yml` in isolation. The applicable order is:

1. Bundled defaults.
2. Committed `.echelon/config.yml`.
3. Legacy project configuration when the canonical file is absent.
4. `.echelon/local.yml` or its legacy equivalent.
5. Applicable environment overrides.

Only an allowlisted subset of resolved workspace and source configuration may
enter the wiki model. The generator must never serialize the full resolved
configuration or expose secrets, credentials, environment values, deployment
settings, or LLM configuration.

The first configurable behavior is:

```yaml
wiki:
  auto_refresh: true
```

`auto_refresh` applies only after the user has explicitly generated the wiki once.
The generated output path is fixed at `.echelon/runtime/wiki/` in the first version.

## Architecture

The generator has four isolated components.

### Discovery

Discovery resolves canonical inputs through the existing workspace, RE publication,
spec resolution, and artifact registry contracts. It does not scan arbitrary
Markdown across the repository.

Canonical inputs include:

- The safe subset of resolved workspace configuration.
- `re/index.json` and published artifacts referenced by the RE publication model.
- Published `specs/<id>-*/` directories.
- Known metadata such as frontmatter, manifests, `targets.yml`, traceability
  matrices, artifact registries, and lifecycle status.

Runtime reasoning journals, transient run state, arbitrary repository Markdown,
and source-code documentation are excluded unless a future design explicitly adds
them as canonical artifact classes.

### Indexing

Indexing parses discovered inputs into a tool-neutral `WikiModel`. Parsers are
specific to known Echelon artifact formats and return structured nodes,
relationships, provenance, and warnings. They do not render Markdown.

### Rendering

Rendering converts `WikiModel` into standard Markdown navigation pages, projected
artifact views, a machine-readable manifest, warnings, and optional viewer
configuration. It writes into a staging directory.

### Publication

Publication validates required pages and links, then atomically replaces
`.echelon/runtime/wiki/`. A failed or interrupted build leaves the previous valid
vault intact.

## Wiki model

Stable identities do not depend on mutable titles:

- Workspace: workspace-root identity.
- Source: configured `sources[].id`.
- Domain: published RE source ID plus domain ID.
- Spec: canonical spec directory ID.
- Artifact: workspace-relative canonical path.
- Requirement or task: spec ID plus its local stable identifier.

This prevents title changes and equivalent IDs in separate specs from colliding.
Filename collisions are resolved with stable source or spec identifiers, never
traversal-order suffixes.

Supported relationship types in the first schema are:

- `contains`
- `targets`
- `derived_from`
- `depends_on`
- `implements`
- `verifies`
- `defers`
- `supersedes`

Every relationship records the artifact and structured field, row, or identifier
that established it. Duplicate identities and contradictory relationships produce
warnings rather than silent winner selection.

## Information architecture

The generated vault has this logical layout:

```text
.echelon/runtime/wiki/
├── Home.md
├── Specs/
│   ├── Index.md
│   └── 001-feature/
│       ├── Overview.md
│       └── Artifacts.md
├── Reverse Engineering/
│   ├── Index.md
│   ├── Sources/
│   └── Domains/
├── Views/
│   ├── Active Work.md
│   ├── Requirements.md
│   ├── Decisions.md
│   ├── Risks and Issues.md
│   └── Verification.md
├── Artifacts/
│   ├── specs/...
│   └── re/...
├── Warnings.md
├── manifest.json
└── .obsidian/
```

### Workspace home

`Home.md` answers:

- What workspace is this?
- Which source repositories does it manage?
- What work is active?
- Which specs are authoring, build-ready, under verification, ready to land, or
  landed?
- What changed recently?
- Which inputs are missing, stale, dirty, or inconsistent?
- Where should a reader begin?

Recent changes are derived from Git history for canonical inputs plus current
working-tree changes relative to `HEAD`. Filesystem modification times are not used
as history or freshness evidence.

### Spec overview

Each spec overview contains:

- Title, purpose, lifecycle status, and implementation targets.
- An ordered path through specification, plan, tasks, and verification evidence.
- Artifact completeness grouped by lifecycle stage.
- Requirement and task counts.
- Open risks, issues, gaps, and deferred scope.
- Related RE sources and domains when explicit evidence supports the relationship.
- Provenance and freshness information.

### Aggregate views

Global views aggregate structured information across specs. They remain indexes,
not sources of truth. Requirements and tasks remain rows linked to projected source
artifacts rather than becoming thousands of individual pages.

### Artifact projections

The `Artifacts/` subtree preserves the original source-relative structure beneath
`Artifacts/specs/` and `Artifacts/re/`. Existing frontmatter remains intact. A
generated banner displays the canonical path and input hash, while `manifest.json`
remains the authoritative provenance record.

Rendering preserves fenced code, embedded examples, and ordinary prose. Relative
links are rewritten only when needed to point to another projected artifact. Known
referenced images and diagrams are copied. Non-text attachments larger than 10 MiB
and unsupported attachment formats are catalogued with canonical paths rather than
copied into the vault.

## Provenance and freshness

`manifest.json` records:

- Generator and wiki schema versions.
- Generation timestamp.
- Workspace root identity and Git revision.
- Whether canonical inputs were dirty.
- Every canonical input path and content hash.
- Every output page.
- Relationship provenance.
- Warnings and validation results.

Generated navigation-page frontmatter contains only `echelon_wiki`, `page_type`,
`stable_id`, and `generated_at`. Artifact projections preserve their existing
frontmatter instead of merging wiki metadata into it. The manifest is authoritative.
Given identical inputs and a fixed clock, generation produces identical paths,
ordering, relationships, warnings, and content hashes.

The wiki represents the current working tree, including uncommitted canonical
artifact changes. It labels dirty input prominently rather than pretending the
view represents only `HEAD`.

## CLI and lifecycle

The initial command surface is:

```bash
echelon wiki build
echelon wiki status
echelon wiki clean
```

### Build

`echelon wiki build` performs a complete rebuild. Full rebuilds are preferred over
incremental mutation in the first version because local parsing is expected to be
cheap and a rebuild cannot accumulate orphaned or stale pages.

On success, the command prints the vault path, the `Home.md` path, and a short note
that Obsidian is an optional recommended viewer. It does not install or launch a
viewer.

### Status

`echelon wiki status` reports one of `absent`, `fresh`, `stale`, or `invalid`, plus:

- Last workspace revision.
- Dirty-input status.
- Added, changed, and removed inputs.
- Generator/schema compatibility.
- A concrete recovery command.

### Clean

`echelon wiki clean` removes only a directory containing a valid Echelon wiki
manifest at the canonical runtime path. It refuses to recursively delete an
unrecognized directory.

## Auto-refresh semantics

Auto-refresh has no watcher. It is triggered only when all of these conditions are
true:

1. A valid generated vault already exists.
2. An Echelon command completes successfully.
3. Canonical wiki inputs under `specs/` or `re/` changed.
4. Resolved `wiki.auto_refresh` is not `false`.

The decision is based on canonical input paths and hashes rather than a fragile
hard-coded command allowlist. Typical triggers include successful Phase A or manual
phase publication, spec scope changes and rewinds, RE publication, delivery report
publication or lifecycle changes, and landing.

Auto-refresh does not run:

- During intermediate agent writes.
- After failed or blocked commands.
- For read-only commands.
- On ordinary filesystem saves.
- After an external Git pull or checkout.
- Before the first explicit `echelon wiki build`.

External Git changes or manual edits make `echelon wiki status` report `stale`.
The user refreshes explicitly with `echelon wiki build`.

Auto-refresh is best effort. Failure never changes the outcome of specification,
RE, delivery, or landing. Echelon preserves the previous valid vault and prints a
warning with the explicit recovery command.

## Error handling

- Missing optional artifacts create visible non-blocking warnings.
- Invalid required workspace or publication metadata aborts generation.
- Broken required navigation links abort publication.
- Broken optional attachment links remain warnings in `Warnings.md`.
- Duplicate or contradictory stable identities remain visible warnings.
- A failed staged build never replaces the current valid vault.
- Errors identify the canonical input and recommended recovery action.

## Safety

The generator must:

- Never modify `specs/`, `re/`, or declared source repositories.
- Never expose secrets or serialize unrestricted resolved configuration.
- Reject discovered paths that escape the workspace or canonical artifact roots.
- Treat symlinks conservatively and never follow them outside allowed roots.
- Replace or delete only a directory with a valid Echelon wiki manifest.
- Avoid network access and LLM invocation.

## Test strategy

### Unit tests

Unit tests cover:

- Configuration cascade and safe-field extraction.
- Canonical artifact discovery.
- Stable node identities and collision handling.
- Known frontmatter and structured-table parsers.
- Relationship provenance.
- Markdown link rewriting without changes inside fenced code.
- Path containment and symlink escapes.
- Secret exclusion.
- Freshness and input hashing.

### Golden tests

Golden-file tests use a fixed clock and revision to verify exact Markdown output,
manifest structure, page ordering, and warnings.

### Fixture workspaces

Fixtures cover:

- Single-repository workspaces.
- Polyrepo workspaces.
- Planning-only workspaces.
- Published RE with multiple sources and domains.
- Specs at every lifecycle stage.
- Missing optional and required artifacts.
- Dirty working trees.
- Renamed and deleted artifacts.
- Unsupported and oversized attachments.

### Integration tests

Integration tests verify:

- Successful atomic publication.
- Failed builds preserve the previous vault.
- Status detects manual and Git changes.
- Auto-refresh runs only after successful canonical mutations.
- Auto-refresh never creates a vault before explicit opt-in.
- Read-only and failed commands do not trigger refresh.
- Clean refuses unrecognized directories.
- All required navigation links resolve.

### Performance

Generation must be offline and linear in the number and total byte size of canonical
inputs. On the project's CI reference runner, a warm-filesystem benchmark containing
100 specs, 2,000 artifacts, and 50 MiB of Markdown must complete a full build in at
most 5 seconds with peak resident memory below 512 MiB. Default auto-refresh does not
ship until this benchmark passes. If full rebuild cost later becomes a measured UX
problem, incremental rendering may be designed against the same `WikiModel` and
manifest contracts.

## Future extensions

Future work may add a static HTML renderer, committed publication mode,
cross-workspace aggregation, richer viewer adapters, or incremental rebuilds.
These extensions must consume the same `WikiModel`; they must not introduce
parallel artifact discovery, relationship inference, or provenance rules.
