# Workspace Contract v1 Design

**Status:** Proposed
**Date:** 2026-07-02
**Tracking:** EGR-073 / GitHub #90
**Deciders:** Echelon maintainers

## Context

Echelon currently accepts several workspace shapes and then compensates later:
branchless workspaces, single repositories, polyrepo orchestration folders,
generated spec-kit runtime state, installed extension copies, harness runs, and
source repositories can all coexist in ways that are only partly explicit.

Recent fixes exposed the cost of that flexibility:

- `.specify/memory/constitution.md` could be tracked even though `.specify/` is
  spec-kit runtime state.
- `echelon land` had to learn how to recover legacy `.specify/` conflicts.
- Polyrepo source-root selection depends on deterministic workspace discovery,
  but scaffolding still lets users create ambiguous layouts.
- Documentation still mixes committed project defaults with runtime extension
  config under `.specify/extensions/echelon/echelon-config.yml`.

The product goal is a boring, repeatable path:

```text
echelon run/continue/resume
-> echelon harness run/resume
-> echelon land
-> done
```

That path should not require manual Git cleanup for known Echelon/spec-kit
runtime artifacts.

## Decision

Define **Workspace Contract v1** and make new Echelon workspaces conform to it.
The core decision is:

- `.specify/` is runtime state and is ignored by workspace Git.
- `.echelon/config.yml` is the committed Echelon workspace/project config.
- `specs/<id>-*/` is the tracked artifact surface for Phase A and verification
  handoffs.
- Source roots are explicit and are never inferred from runtime directories.
- Echelon commands validate the contract early and block with migration guidance
  instead of supporting arbitrary free-form layouts.

## Options Considered

### Option A: Keep `.specify/extensions/echelon/echelon-config.yml` as committed config

| Dimension | Assessment |
|---|---|
| Complexity | Low short term, high long term |
| Compatibility | High with current paths |
| Operational clarity | Poor |
| Polyrepo fit | Weak |

**Pros:**
- Minimal immediate code churn.
- Matches current config loader assumptions.

**Cons:**
- Contradicts the desired `.specify/` gitignore contract.
- Keeps runtime extension installation and committed config in the same tree.
- Continues to create edge cases around stale extension copies and runtime drift.

### Option B: Track selected exceptions under `.specify/`

Example:

```gitignore
/.specify/*
!/.specify/memory/
!/.specify/memory/constitution.md
!/.specify/extensions/echelon/echelon-config.yml
```

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Compatibility | Medium |
| Operational clarity | Poor |
| Polyrepo fit | Weak |

**Pros:**
- Preserves spec-kit paths.
- Avoids introducing a new config location.

**Cons:**
- `.specify/` remains both runtime and source of truth.
- Gitignore exceptions are brittle and hard to explain.
- The constitution source remains split between spec-kit memory and published
  spec snapshots.

### Option C: Move committed Echelon config to `.echelon/config.yml`

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Compatibility | Requires migration |
| Operational clarity | Strong |
| Polyrepo fit | Strong |

**Pros:**
- Separates committed Echelon contract from spec-kit runtime state.
- Gives workspace doctor/init/migration one clear target.
- Supports single-repo, polyrepo, and planning-only workspaces with one model.
- Makes `.specify/` ignoring simple and defensible.

**Cons:**
- Requires config-loader compatibility and migration support.
- Existing projects need a one-time migration.
- Documentation and installed extension templates need coordinated updates.

## Chosen Approach

Use **Option C**.

Workspace Contract v1 introduces `.echelon/config.yml` as the committed config
and treats `.specify/` as ignored runtime state. Existing
`.specify/extensions/echelon/echelon-config.yml` remains a compatibility input
during migration, but it is no longer the canonical committed config location
for new workspaces.

## Workspace Layout

### Single-Repo Source Workspace

```text
my-app/
  .git/
  .gitignore
  .echelon/
    config.yml
  .specify/                 # ignored runtime
  runs/                     # ignored runtime
  specs/
    001-feature/
      spec.md
      plan.md
      tasks.md
      constitution.md
  src/
  tests/
  pyproject.toml
```

Workspace model:

```yaml
workspace:
  git_role: source
sources:
  - id: "."
    path: "."
```

### Polyrepo Orchestration Workspace

```text
workspace/
  .git/
  .gitignore
  .echelon/
    config.yml
  .specify/                 # ignored runtime
  runs/                     # ignored runtime
  specs/
    001-feature/
      spec.md
      plan.md
      tasks.md
      constitution.md
  og-platform/              # ignored source repo unless submodule
    .git/
  pbg-api/                  # ignored source repo unless submodule
    .git/
```

Workspace model:

```yaml
workspace:
  git_role: orchestration
sources:
  - id: og-platform
    path: og-platform
  - id: pbg-api
    path: pbg-api
```

### Planning-Only Workspace

```text
planning-workspace/
  .git/
  .gitignore
  .echelon/
    config.yml
  .specify/                 # ignored runtime
  runs/                     # ignored runtime
  specs/
```

Workspace model:

```yaml
workspace:
  git_role: orchestration
sources: []
```

Planning-only workspaces can run Phase A spec work. Harness build blocks until a
source root is added or selected.

## Tracking Contract

### Always Tracked

- `.gitignore`
- `.echelon/config.yml`
- `specs/<id>-*/spec.md`
- `specs/<id>-*/requirements.lexicon.md`
- `specs/<id>-*/plan.md`
- `specs/<id>-*/tasks.md`
- `specs/<id>-*/constitution.md`
- `specs/<id>-*/ARTIFACTS.md`
- `specs/<id>-*/fulfillment-report.md` when produced by verification

### Conditionally Tracked

- `.echelon/workspace-manifest.json` if we decide to persist a reviewed
  workspace contract instead of only deriving it.
- `knowledge-base/**` only after a separate policy classifies which entries are
  durable project memory versus local learning cache.
- Child source roots in polyrepo mode only if the user intentionally uses
  submodules or a monorepo-with-source-at-root shape.

### Always Ignored

- `.specify/**`
- `runs/**`
- `.claude/**`
- `.echelon/runtime/**`
- `.echelon/cache/**`
- Build/test caches such as `.pytest_cache/`, `.hypothesis/`, `.ruff_cache/`,
  `node_modules/`, and language-specific generated artifacts.

## Configuration Contract

### Canonical Committed Config

Path:

```text
.echelon/config.yml
```

Responsibilities:

- Workspace role and source roots.
- Harness config that should be stable across developers.
- Lexicon/artifact config.
- MemPalace wing identity.
- Container provider defaults when intentionally shared.

### Local Runtime Overrides

Allowed ignored paths:

```text
.echelon/local.yml
.specify/extensions/echelon/local-config.yml
```

Responsibilities:

- Developer-local provider paths.
- Local model/tool permissions.
- Local Docker/Podman differences.
- Temporary extraction overrides.

### Compatibility Read Order

During migration:

1. Built-in defaults.
2. `.echelon/config.yml`.
3. Legacy `.specify/extensions/echelon/echelon-config.yml` when the canonical
   config is absent.
4. Local ignored overrides.
5. Environment variables.
6. CLI arguments.

After migration hardening, new workspaces should block if only the legacy config
exists and no migration has been run.

## Source-Root Contract

Source roots are deterministic workspace facts, not late-stage guesses.

Rules:

1. `sources: [.]` means the workspace root is also the implementation repo.
2. `sources: [repo-a, repo-b]` means the workspace root is orchestration only.
3. `sources: []` means planning-only; harness build is blocked.
4. In orchestration workspaces, source root directories are ignored by workspace
   Git unless they are intentionally configured as submodules.
5. Harness build, verify, and land operate on the selected source root, while
   specs and run metadata remain in the workspace root.
6. If multiple source roots exist and no target is set, semi/guided modes block
   with a target-selection message; banzai may select only if the deterministic
   confidence is high enough and the choice is recorded.

## Scaffolding Contract

`echelon init` should create or verify:

```text
.git/
.gitignore
.echelon/config.yml
.specify/                 # installed runtime, ignored
specs/
runs/                     # ignored
```

For polyrepo workspaces, `echelon init` should add discovered source roots to
`.gitignore` unless they are submodules.

Example generated `.gitignore` block:

```gitignore
# Echelon/spec-kit runtime
/.specify/
/runs/
/.claude/
/.echelon/runtime/
/.echelon/cache/

# Polyrepo source roots
/og-platform/
/pbg-api/
```

`echelon init` should never tell users to `git add .specify`.

## Doctor Contract

Add or harden `echelon workspace doctor` to validate:

- Workspace root is Git-backed.
- `.specify/` is ignored.
- `.specify/**` has no tracked files.
- `.echelon/config.yml` exists for new-layout workspaces.
- Legacy config exists only as a migration source or runtime mirror.
- `specs/` is present and not ignored.
- Source roots in config exist.
- Polyrepo source roots are ignored by workspace Git unless submodules.
- No source root is accidentally inside `.specify/`, `runs/`, or `specs/`.
- Planning-only workspaces are marked as not buildable.

Doctor should produce machine-readable findings and human CLI output.

## Migration Contract

Add or harden `echelon workspace migrate` to:

1. Copy canonical shared config from
   `.specify/extensions/echelon/echelon-config.yml` to `.echelon/config.yml`
   when `.echelon/config.yml` is absent.
2. Preserve local-only overrides under ignored local config.
3. Add `.specify/`, `runs/`, `.claude/`, `.echelon/runtime/`, and
   `.echelon/cache/` to `.gitignore`.
4. Untrack `.specify/**`.
5. Keep `specs/<id>-*/constitution.md` as the tracked constitution handoff.
6. Detect child source roots and add them to `.gitignore` in orchestration
   workspaces.
7. Print the exact staged changes before committing.

Migration should be idempotent.

## Command Enforcement

### Phase A Commands

`echelon run`, `continue`, `resume`, and targeted phase replay should:

- Require a Git-backed workspace except for explicit legacy recovery.
- Require valid workspace contract or actionable migration path.
- Write run-local state to `runs/`.
- Publish durable artifacts to `specs/`.
- Treat `.specify/` as runtime only.

### Harness Commands

`echelon harness run/resume` should:

- Require a valid workspace contract.
- Require explicit source root selection when ambiguous.
- Copy needed runtime extension files into worktrees without expecting them to
  be tracked.
- Refuse to build planning-only workspaces.

### Land Command

`echelon land` should:

- Read readiness from the feature branch as implemented in EGR-070.
- Autoresolve known runtime-state transitions as implemented in EGR-072.
- Block on real source/spec semantic conflicts.
- Never ask users to hand-resolve `.specify/` runtime conflicts.

## Testing Strategy

Add contract tests for:

- New single-repo scaffold.
- New polyrepo scaffold.
- Planning-only scaffold.
- Legacy `.specify/extensions/echelon/echelon-config.yml` migration.
- Tracked `.specify/**` detection and automatic untracking.
- Source-root ignore generation.
- Harness target resolution from `.echelon/config.yml`.
- Config precedence.
- Land recovery for runtime-state conflicts.

Keep existing unit tests for workspace model discovery, migration, land, and
target detection; expand them around the new canonical config path.

## Rollout Plan

1. Introduce `.echelon/config.yml` loader support while keeping legacy config
   compatibility.
2. Add scaffold/doctor/migrate contract checks.
3. Update docs and command help.
4. Update `echelon init` and workspace migration scripts.
5. Add warnings for legacy config-only workspaces.
6. Later, convert warnings into blockers for new workspaces.

## Consequences

### Benefits

- New workspaces become predictable.
- `.specify/` stops leaking into Git state.
- Polyrepo target selection becomes explicit and auditable.
- Land/harness recovery has fewer historical edge cases to support.
- Echelon config is visible and committed in a tool-owned path.

### Costs

- Existing users need migration support.
- Config loading touches several Python paths and tests.
- Docs and installed extension templates need coordinated updates.
- Some compatibility code remains until old workspaces age out.

## Open Policy Item

`knowledge-base/**` needs a separate decision. It may contain durable project
memory, local learning cache, or both. Workspace Contract v1 should not classify
it until that policy is explicit.

## Acceptance Criteria

- A new workspace initialized by Echelon has no tracked `.specify/**` files.
- A migrated workspace has `.echelon/config.yml` committed and `.specify/`
  ignored.
- Existing legacy workspaces receive clear migration guidance before normal
  commands proceed.
- `echelon run/continue/resume -> echelon harness run/resume -> echelon land`
  does not require manual Git cleanup for known Echelon/spec-kit runtime files.
- Polyrepo workspaces cannot accidentally build the orchestration root when a
  source root should be selected.

