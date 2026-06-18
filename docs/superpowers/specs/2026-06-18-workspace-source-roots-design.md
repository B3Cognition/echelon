# Workspace Source Roots Design

## Summary

Echelon should treat every project as a workspace with zero or more source roots:

```text
workspace_root
  .specify/
  specs/
  runs/
  source_roots[0..N]
```

This replaces the current implicit split between "single repo" and "polyrepo" with one model:

- `sources: [.]` is a traditional single-repo project.
- `sources: [repo-a, repo-b]` is a polyrepo workspace.
- `sources: []` is a planning/spec-only workspace and cannot run harness build until sources exist.

The workspace root is where Echelon and spec-kit state live. Source roots are where implementation code lives. A workspace can be a lightweight Git repo for specs and run metadata without being an implementation repo.

## Problem

Current behavior overuses `.git` presence as identity:

- If the root has `.git`, tools may treat it as the application repo.
- If the root has no `.git`, `speckit.specify` cannot create branches for spec work.
- If nested source repos exist, reverse engineering and harness target selection can disagree about what the project is.
- Branchless workspaces make recovery and landing ambiguous.

The observed `og20` failure is the concrete symptom:

- `og20` is an orchestration workspace containing multiple cloned repos.
- It was not a Git repo, so spec-kit skipped branch creation.
- Echelon could create a spec directory but had no durable workspace branch semantics.
- A lightweight workspace Git repo would solve spec versioning, but only if Echelon does not mistake the workspace repo for source code.

## Goals

1. Make `workspace_root` and `source_roots[]` first-class deterministic data.
2. Require a Git-backed workspace for normal Echelon operation.
3. Keep single-repo behavior working by representing it as `source_roots: [.]`.
4. Make reverse engineering scan source roots, not the workspace root by accident.
5. Make harness build, resume, verify, and land target source roots only.
6. Provide a safe migration path for existing single-repo and polyrepo users.
7. Fail early with actionable messages when a workspace is not initialized correctly.

## Non-Goals

- Do not implement general branchless workspace support as a normal mode.
- Do not require child repos to be Git submodules.
- Do not force multi-target implementation in the first migration stage.
- Do not migrate existing specs automatically without a dry-run report.
- Do not change spec-kit templates or branch naming in this design.

## Core Model

Persist the workspace model in Echelon state and optionally in config.

```yaml
workspace:
  root: /absolute/path/to/workspace
  git_role: orchestration | source
  git_present: true

sources:
  - id: "."
    path: "."
    git_role: source
    git_present: true
    project_markers:
      - package.json
```

For a polyrepo workspace:

```yaml
workspace:
  root: /Users/michalbachorik/work/sync/ui/og20
  git_role: orchestration
  git_present: true

sources:
  - id: og-platform
    path: og-platform
    git_role: source
    git_present: true
    project_markers:
      - package.json
      - nx.json
  - id: pbg-api
    path: pbg-api
    git_role: source
    git_present: true
    project_markers:
      - pom.xml
```

Definitions:

- `workspace.root`: absolute directory containing `.specify/`, `specs/`, and `runs/`.
- `workspace.git_role=orchestration`: Git tracks Echelon/spec artifacts, not application implementation.
- `workspace.git_role=source`: workspace root is also the implementation repo.
- `sources[].path`: path relative to `workspace.root`; `.` is allowed.
- `sources[].id`: stable display and target identifier.
- `.git` is evidence, not identity. Identity comes from the workspace model.

## Discovery Rules

Discovery should produce a `workspace-manifest.json` artifact:

```json
{
  "schema_version": 1,
  "workspace": {
    "root": "/abs/path",
    "git_role": "orchestration",
    "git_present": true
  },
  "sources": [
    {
      "id": "og-platform",
      "path": "og-platform",
      "git_present": true,
      "project_markers": ["package.json", "nx.json"],
      "source_file_count": 7142
    }
  ]
}
```

Algorithm:

1. Identify `workspace.root` as the directory where Echelon is initialized.
2. Require `workspace.root/.git` for normal `echelon run`, `continue`, `harness run`, and `land`.
3. Scan immediate children for source markers and `.git` directories or files.
4. If children contain source repos:
   - Set `workspace.git_role=orchestration`.
   - Set `sources[]` to matching children.
   - Do not include `.` as a source unless explicitly configured.
5. If no child source repos exist and root has source markers:
   - Set `workspace.git_role=source`.
   - Set `sources: [{id: ".", path: "."}]`.
6. If no child source repos and root has no source markers:
   - Set `workspace.git_role=orchestration`.
   - Set `sources: []`.
   - Allow specification phases, but block harness build with "no source roots".

## Workspace Git Requirement

Branchless workspace should not be a normal supported mode. If `workspace.root/.git` is absent, Echelon should block with a concrete init recipe:

```text
✗ Echelon workspace root is not a Git repo.

Echelon requires workspace Git so specs, run state, and recovery metadata have durable version history.

Fix:
  git init
  printf "/og-platform/\n/pbg-api/\n" >> .gitignore
  git add .gitignore .specify specs
  git commit -m "chore: initialize echelon workspace"
```

For a source-root single repo, this is already satisfied.

For a polyrepo workspace, the `.gitignore` should ignore child source repos unless the user explicitly wants submodules:

```gitignore
/og-platform/
/pbg-api/
/fet-frontend-libs/
/pe-argocd-deployments-og/
/pressbox-terraform/
/runs/build-*/
/runs/verify-*/
.codegraph/
.DS_Store
```

## Spec Creation

`speckit.specify` always runs in `workspace.root`.

Expected behavior:

- Workspace Git branch is created for spec work.
- Spec directory is created under `workspace.root/specs/{NNN}-{feature}`.
- State records `workspace_branch`, `spec_dir`, and `workspace_git_role`.
- Source target selection is not required during early spec creation, but it must be resolved before harness build.

If `workspace.git_role=orchestration`, branch creation is still valid because the branch tracks specs and Echelon artifacts only.

## Reverse Engineering

Reverse engineering should operate over `sources[]`.

Rules:

- For `sources: [.]`, behavior is equivalent to current single-repo RE.
- For `sources: [repo-a, repo-b]`, run extraction per source root.
- CodeGraph runs per source root, not at workspace root.
- Workspace root is analyzed only for Echelon/spec artifacts and never counted as implementation code unless `sources[].path == "."`.
- `repos-manifest.json` can remain for compatibility, but new code should prefer `workspace-manifest.json`.

The RE overview must use the terms "workspace" and "source roots", not "monorepo of monorepos".

## Harness Build

Harness must consume the workspace model:

1. Resolve `workspace.root` and `spec_dir` from workspace state.
2. Resolve build targets from spec frontmatter or deterministic target detection over `sources[]`.
3. If `sources.length == 0`, block before build.
4. If `sources.length == 1` and no explicit target is set, use that source root.
5. If `sources.length > 1` and no explicit target is set, block in semi/guided or ask COMMANDER in banzai.
6. Never build the workspace root unless the selected source path is `.`.

Worktree behavior:

- Workspace worktree/branch owns spec and task artifacts.
- Source repo worktrees/branches own implementation artifacts.
- For single repo, these are the same checkout and existing behavior remains.
- For polyrepo, harness state must store both workspace commit/branch and source repo commit/branch.

## Land And Resume

Landing must report two classes of commits:

```text
workspace:
  branch: 006-element-creator
  commit: abc123

sources:
  og-platform:
    branch: 006-element-creator
    commit: def456
  pbg-api:
    branch: 006-element-creator
    commit: fed789
```

Resume/recover must use workspace state as the source of truth:

- `spec_dir` is always under `workspace.root`.
- `tasks.md` and fulfillment artifacts are read from workspace.
- Salvage commits in source roots are applied to source roots.
- Salvage commits in workspace are applied to workspace.

## Migration Path

### Stage 0: Design Branch

Create and test the design in a dedicated branch. Do not ship behavior changes from `main`.

### Stage 1: Model And Reporting Only

Add workspace discovery and `workspace-manifest.json`.

Behavior:

- Existing commands still work.
- CLI banners print workspace/source model.
- No command blocks solely because the workspace model is absent.
- Tests cover single repo, polyrepo with orchestration Git, polyrepo without Git, and spec-only workspace.

### Stage 2: Warnings For Branchless Polyrepo Workspaces

For `sources.length > 1` and `workspace.git_present=false`, print a warning before spec creation:

```text
⚠ workspace root is not Git-backed; future Echelon versions will require workspace Git.
```

Do not block yet. This lets us test in real projects without breaking users.

### Stage 3: Harness Uses Workspace/Source Split

Update harness target selection and build worktree setup to consume `workspace-manifest.json`.

Behavior:

- Single repo remains unchanged through `sources: [.]`.
- Polyrepo build never targets workspace root by default.
- Missing target in multi-source workspace blocks before build with a clear remediation.

### Stage 4: Require Workspace Git For New Polyrepo Runs

New polyrepo runs block if workspace Git is missing.

Existing active runs may continue with a compatibility warning if their state predates the requirement.

### Stage 5: Remove Branchless Compatibility

After one release cycle:

- `echelon run`, `continue`, `harness run`, and `land` require `workspace.git_present=true`.
- Branchless workspaces can only run `echelon diagnose workspace` or `echelon init workspace`.

## Testing Strategy

Unit tests:

- Workspace discovery:
  - root Git + no children => `sources: [.]` when root has project markers.
  - root Git + child Git repos => `workspace.git_role=orchestration`, child sources only.
  - root no Git + child Git repos => warning/block by stage.
  - child `.git` file is treated as Git-present.
- Target detection:
  - one source auto-selects.
  - multiple sources require explicit target unless confidence is deterministic.
  - workspace root is never a candidate unless source path is `.`.

Integration tests:

- `echelon run` in a single repo still creates specs and advances.
- `echelon run` in a lightweight workspace creates spec branch in workspace Git.
- RE outputs per-source artifacts and aggregate workspace manifest.
- Harness run in a multi-source workspace blocks without `targets:`.
- Harness run with `targets: [og-platform]` builds only `og-platform`.
- Resume and salvage preserve workspace/source separation.

Manual test matrix:

| Scenario | Expected |
|---|---|
| Single Git repo | No visible behavior change |
| Polyrepo workspace Git + ignored child repos | Specs branch in workspace, build targets child |
| Polyrepo workspace no Git | Stage warning then later hard block |
| Spec-only workspace Git | Spec phases allowed, harness build blocked |
| Child repos as submodules | `.git` file detected and source roots found |

## Rollout And Safety

Ship this behind staged behavior:

1. Introduce model and diagnostics.
2. Exercise on internal projects like `og20`.
3. Turn harness over to the model.
4. Require workspace Git only after diagnostics are proven.

Every stage should be releasable independently. Do not merge the final hard block until single-repo and polyrepo harness tests are stable.

## Open Decisions

1. Should `runs/spec-*/state.json` be committed in the workspace repo, or should only specs/config be committed?
2. Should Echelon provide `echelon workspace init` to generate `.gitignore` and initial commit?
3. Should source roots be stored in `echelon-config.yml`, `workspace-manifest.json`, spec frontmatter, or all three with precedence?
4. How should multi-target landing create PRs when each child repo has a different remote?

## Recommendation

Use the workspace/source-roots model and make lightweight workspace Git the required normal mode. Keep branchless support only during migration warnings, then remove it as a supported operating mode.

This is a bigger change than the local polyrepo patches, but it reduces the long-term surface area: Echelon stops guessing whether the current directory is "the app" and instead operates from an explicit workspace model.
