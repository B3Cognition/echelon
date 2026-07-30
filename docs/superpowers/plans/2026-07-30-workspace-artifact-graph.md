# Workspace Artifact Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare and compose per-spec artifact graphs into one deterministic,
auditable, viewable workspace graph using the existing memory and graph
pipelines.

**Architecture:** A new `workspace_graph` module discovers canonical specs,
classifies their persisted graphs through the existing live per-spec audit,
normalizes shared identities, and writes a local derived graph. The explicit
workspace refresh operation audits and invokes existing memory and per-spec
graph refresh APIs only where stale; other workspace commands do not mutate
upstream state. A separate workspace audit recomputes receipts and compares
them with persisted state. Existing visualization becomes scope-neutral and
filters one embedded graph client-side; Typer exposes the lifecycle beneath
`echelon graph workspace`.

**Tech Stack:** Python 3.11+, dataclasses, JSON/YAML, Typer, Cytoscape.js,
pytest.

## Global Constraints

- Persisted per-spec graphs remain the only per-spec graph authority.
- `workspace refresh --write` may orchestrate existing memory refresh and
  per-spec graph build APIs; it must not duplicate their logic.
- `workspace build`, `audit`, `view`, and `export`, plus refresh without
  `--write`, never mutate memory or persisted per-spec graphs.
- Audit before refresh, refresh shared RE once, and skip current memory domains
  and current per-spec graphs.
- Read only canonical direct children of `specs/`; exclude symlinks and runs.
- Read only canonical `.echelon/config.yml`; do not use heuristic or legacy
  workspace discovery.
- Preserve all existing per-spec graph schemas and CLI behavior.
- Write workspace artifacts only below `.echelon/runtime/graph/`.
- Replace persisted output atomically and preserve the prior graph on failure.
- Produce useful partial graphs while making every excluded member visible.
- Preserve unrelated in-progress workspace changes and stage explicit files.

---

### Task 1: Deterministic Workspace Composition

**Files:**
- Create: `src/echelon/workspace_graph.py`
- Create: `tests/unit/test_workspace_graph.py`

**Interfaces:**
- Consumes: canonical `.echelon/config.yml`, direct canonical spec
  directories, persisted `spec-artifact-graph.json` files, and
  `audit_spec_graph`.
- Produces:
  - `WorkspaceGraphError`
  - `WorkspaceCompositionIssue`
  - `WorkspaceGraphMember`
  - `WorkspaceArtifactGraph`
  - `WorkspaceGraphBuildResult`
  - `discover_canonical_spec_dirs(project_root: Path) -> tuple[Path, ...]`
  - `build_workspace_graph(project_root: Path) -> WorkspaceGraphBuildResult`
  - `render_workspace_graph(graph: WorkspaceArtifactGraph) -> bytes`
  - `workspace_graph_path(project_root: Path) -> Path`
  - `write_workspace_graph(graph, project_root) -> Path`
  - `load_workspace_graph_document(project_root: Path) -> dict[str, object]`

- [ ] **Step 1: Add canonical discovery and deterministic rendering tests**

Create fixtures with two direct spec directories in reverse creation order,
one nested run-local spec, and one symlink. Assert:

```python
assert [path.name for path in discover_canonical_spec_dirs(tmp_path)] == [
    "001-alpha",
    "002-beta",
]
assert render_workspace_graph(first.graph) == render_workspace_graph(second.graph)
assert first.graph.to_dict()["scope"] == "workspace"
assert first.graph.to_dict()["nodes"][0]["id"] == "artifact:re/workspace/overview.md"
```

Also assert that missing/invalid `.echelon/config.yml` and no canonical specs
raise bounded `WorkspaceGraphError` values rather than activating heuristic
workspace discovery.

- [ ] **Step 2: Run the focused test and confirm the module is absent**

Run:

```bash
python -m pytest -q tests/unit/test_workspace_graph.py
```

Expected: collection failure for `echelon.workspace_graph`.

- [ ] **Step 3: Implement the workspace model and strict discovery**

Use frozen dataclasses. `WorkspaceGraphBuildResult` carries `graph` plus sorted
`issues`; issues are audit inputs and are not serialized as another graph
authority. `WorkspaceArtifactGraph.to_dict()` must emit exactly:

```python
{
    "schema_version": 1,
    "generator_version": ...,
    "scope": "workspace",
    "workspace_name": ...,
    "source_set_digest": ...,
    "member_state_digest": ...,
    "members": ...,
    "inputs": ...,
    "nodes": ...,
    "edges": ...,
}
```

Parse canonical config with `yaml.safe_load`, accepting only
`workspace.git_role` and sorted `sources[].id`/`sources[].path` in the hashed
projection. Reject duplicate source IDs, non-list `sources`, missing paths, and
path escapes with `WorkspaceGraphError`.

- [ ] **Step 4: Add member classification tests**

Monkeypatch `audit_spec_graph` with `pass`, `warn`, `fail`, and `unavailable`
reports. Assert:

```python
assert included.properties["composition_status"] == "included"
assert excluded.properties == {
    "spec_id": "002-beta",
    "composition_status": "excluded",
    "member_audit_status": "fail",
    "exclusion_reason": "member_graph_stale",
}
assert [member.included for member in result.graph.members] == [True, False]
assert result.issues[0].subject_id == "spec:002-beta"
```

Add malformed JSON, wrong schema, top-level/member Spec ID mismatch, and missing
graph cases. Assert unhealthy members become placeholders and no per-spec
builder is called.

- [ ] **Step 5: Implement member receipts and partial composition**

For each member:

1. read and validate exact graph bytes;
2. verify the discovered directory, top-level `spec_id`, and Spec node agree;
3. hash graph bytes;
4. call the existing live audit;
5. hash canonical `audit.to_dict()` JSON;
6. include only `pass`/`warn`.

Do not read per-spec audit sidecars.

- [ ] **Step 6: Add shared identity and workspace-edge tests**

Build two healthy member graphs sharing one RE artifact and drawer. Assert:

```python
assert ids.count("artifact:re/workspace/overview.md") == 1
assert ids.count("drawer:shared-re-drawer") == 1
assert artifact.properties["member_specs"] == ["001-alpha", "002-beta"]
assert shared_edge.properties["member_specs"] == ["001-alpha", "002-beta"]
```

Add assertions for:

- `workspace:current -> CONTAINS_SPEC -> spec:*`;
- `spec:* -> TARGETS -> source:*`;
- valid `SUPERSEDES`;
- unresolved targets and missing superseded specs recorded as composition
  warnings;
- conflicting normalized node or edge properties raising
  `WorkspaceGraphError`.

- [ ] **Step 7: Implement normalization and workspace-only relationships**

Normalize only `Artifact` by `properties.path` and `MemPalaceDrawer` by
`properties.drawer_id`. Keep all spec-owned IDs unchanged. Merge identical
properties with sorted `member_specs`; fail before write on any other property
conflict.

Use `read_frontmatter` and `read_target_entries` for workspace-only metadata.
Match a target by configured source ID first, then by exact configured source
path. Do not infer from source contents.

- [ ] **Step 8: Add and implement atomic-write coverage**

Patch `os.replace` to observe publication. Force a structural conflict and
assert the previous graph bytes remain unchanged. Implement sibling temporary
write, flush/fsync, `os.replace`, and best-effort temporary cleanup following
the existing `spec_lifecycle` atomic-write pattern.

- [ ] **Step 9: Run composition tests**

Run:

```bash
python -m pytest -q tests/unit/test_workspace_graph.py
```

Expected: all tests pass.

- [ ] **Step 10: Commit Task 1**

```bash
git add src/echelon/workspace_graph.py tests/unit/test_workspace_graph.py
git commit -m "Add workspace graph composition"
```

---

### Task 2: Workspace Freshness Audit

**Files:**
- Create: `src/echelon/workspace_graph_audit.py`
- Create: `tests/unit/test_workspace_graph_audit.py`

**Interfaces:**
- Consumes: persisted or in-memory `WorkspaceArtifactGraph` plus fresh
  `build_workspace_graph` receipts.
- Produces:
  - `WorkspaceGraphFinding`
  - `WorkspaceGraphAuditReport`
  - `audit_workspace_graph(project_root, candidate: WorkspaceGraphBuildResult | None = None) -> WorkspaceGraphAuditReport`
  - `write_workspace_graph_audit(report, project_root) -> Path`

- [ ] **Step 1: Add report determinism and status tests**

Test stable finding identity and ordering:

```python
assert report.to_dict()["scope"] == "workspace"
assert [row["id"] for row in report.to_dict()["findings"]] == sorted(
    row["id"] for row in report.to_dict()["findings"]
)
assert passing.status == "pass"
assert warning.status == "warn"
assert failed.status == "fail"
assert unavailable.status == "unavailable"
```

Keep exit-code mapping in CLI so the audit layer does not depend on command
adapters.

- [ ] **Step 2: Add stale-transition tests**

Cover:

- workspace graph missing or malformed;
- canonical spec added or removed;
- member graph bytes changed;
- live member audit hash/status changed;
- member source-set or memory-state digest changed;
- config, `spec.md`, or `targets.yml` changed;
- currently unresolved target or absent superseded spec;
- no usable member.

Assert exact codes such as:

```python
{
    "workspace_member_graph_changed",
    "workspace_member_audit_changed",
    "workspace_source_set_stale",
    "workspace_member_state_stale",
}
```

- [ ] **Step 3: Implement candidate-aware audit**

`candidate=None` loads the persisted workspace graph. A supplied
`WorkspaceGraphBuildResult` audits its graph and composition issues directly so
`workspace refresh` without `--write` previews the newly composed graph rather
than an older file.

Recompute current state through `build_workspace_graph`; do not write or
refresh upstream state. Compare digests first, then emit member-specific
diagnostics. Normalize duplicate `(code, subject_id)` findings.

- [ ] **Step 4: Implement status and atomic audit writes**

Use:

- `pass` for no findings;
- `warn` for warnings only and all members usable;
- `fail` when any member is excluded or any error exists;
- `unavailable` for failed canonical discovery, zero specs, or zero usable
  members.

Write the audit JSON atomically below `.echelon/runtime/graph/`.

- [ ] **Step 5: Run audit and existing per-spec graph tests**

Run:

```bash
python -m pytest -q \
  tests/unit/test_workspace_graph.py \
  tests/unit/test_workspace_graph_audit.py \
  tests/unit/test_spec_graph.py \
  tests/unit/test_spec_graph_audit.py
```

- [ ] **Step 6: Commit Task 2**

```bash
git add src/echelon/workspace_graph_audit.py tests/unit/test_workspace_graph_audit.py
git commit -m "Add workspace graph freshness audit"
```

---

### Task 3: Scope-Neutral Scalable Visualization

**Files:**
- Modify: `src/echelon/graph_visualization.py`
- Modify: `tests/unit/test_graph_visualization.py`
- Create: `tests/unit/test_workspace_graph_visualization.py`

**Interfaces:**
- Consumes: either spec or workspace graph documents and either audit report
  shape through `to_dict()`, `status`, and `findings`.
- Preserves: `load_graph_document`, `filter_graph`, `render_graph_dot`, and
  `render_graph_html`.
- Adds: workspace-only `portfolio` lens and scope-neutral title selection.

- [ ] **Step 1: Add regression tests for unchanged per-spec output**

Keep all existing viewer tests green and add assertions that spec documents do
not expose `portfolio`.

- [ ] **Step 2: Add failing workspace visualization tests**

Assert:

```python
html = render_graph_html(workspace_document, audit, ...)
assert '"scope": "workspace"' in html
assert 'value="portfolio"' in html
assert '"views"' not in html
assert html.count('"elements"') == 1

dot = render_graph_dot(workspace_document, audit, lens="portfolio")
assert 'workspace:current' in dot
assert 'CONTAINS_SPEC' in dot
```

Also test `exceptions`, search-safe JSON, missing edge endpoints, and a
placeholder-only unavailable workspace graph.

- [ ] **Step 3: Generalize graph and audit labels**

Select title from:

1. `spec_id` for spec scope;
2. `workspace_name` for workspace scope;
3. a bounded fallback such as `"Echelon graph"`.

Do not require `SpecGraphAuditReport` as the concrete type; use a local
`Protocol` or structural access.

- [ ] **Step 4: Replace duplicated lens payloads**

Embed one canonical Cytoscape element list plus:

- graph scope;
- available lenses;
- lens-to-edge-type rules;
- exception subject IDs;
- audit payload.

Filter elements in the browser when the lens changes. Preserve endpoint
integrity and existing dense-label behavior. Add `portfolio` edge types
`CONTAINS_SPEC`, `TARGETS`, and `SUPERSEDES` only for workspace scope.

- [ ] **Step 5: Run visualization tests and inspect generated HTML size**

Run:

```bash
python -m pytest -q \
  tests/unit/test_graph_visualization.py \
  tests/unit/test_workspace_graph_visualization.py
```

Generate a synthetic multi-spec viewer and assert its HTML contains one graph
element payload rather than one copy per lens.

- [ ] **Step 6: Commit Task 3**

```bash
git add \
  src/echelon/graph_visualization.py \
  tests/unit/test_graph_visualization.py \
  tests/unit/test_workspace_graph_visualization.py
git commit -m "Scale graph viewer for workspace graphs"
```

---

### Task 4: Workspace Graph CLI

**Files:**
- Create: `src/echelon/workspace_graph_refresh.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_graph.py`
- Create: `tests/unit/test_workspace_graph_refresh.py`
- Create: `tests/unit/test_cli_workspace_graph.py`

**Interfaces:**
- Produces:
  - `echelon graph workspace build [--write]`
  - `echelon graph workspace audit [--json] [--write]`
  - `echelon graph workspace refresh [--write]`
  - `echelon graph workspace view [--lens] [--output] [--no-open]`
  - `echelon graph workspace export [--format dot] [--lens] [--output]`

- [ ] **Step 1: Add failing help and lifecycle tests**

Assert the command hierarchy exists and no selector is required:

```python
result = runner.invoke(app, ["graph", "workspace", "--help"])
assert result.exit_code == 0
assert all(name in result.output for name in ("build", "audit", "refresh", "view", "export"))
```

Test build without `--write`, build with `--write`, JSON-only audit output,
refresh candidate audit behavior, and `0/1/2` status mapping.

- [ ] **Step 2: Add bounded upstream-refresh tests**

For `build`, `audit`, `view`, `export`, and refresh without `--write`,
monkeypatch these to fail if invoked:

```python
mine_spec_requirements
mine_re_memory
mine_spec_evidence_memory
write_spec_graph
```

The existing live per-spec audit may call `build_spec_graph` to reconstruct a
current in-memory candidate for comparison. That is read-only and is not an
upstream persisted rebuild.

For `refresh --write`, assert:

- shared RE is audited and refreshed at most once;
- requirement and evidence memory are audited per canonical spec and mined
  only when stale and applicable;
- current member graphs are not rewritten;
- missing or stale member graphs are rebuilt through the existing builder;
- current member graphs with non-rebuildable coherence findings are reported
  but not rewritten on every refresh;
- one member failure does not prevent later members from refreshing;
- the final candidate is composed from the exact persisted member graph bytes.

Keep these decisions in `workspace_graph_refresh.py`, returning deterministic
per-domain/member outcomes for CLI rendering. The service calls existing audit,
mine, cleanup, graph build, and graph write APIs; it must not duplicate their
reconciliation or graph construction logic.

- [ ] **Step 3: Register and implement the workspace sub-Typer**

Add `graph_workspace_app` beneath `graph_app`. Keep existing
`echelon graph <command> <spec>` commands unchanged.

`refresh` must:

1. remain non-mutating without `--write`;
2. with `--write`, audit and conditionally refresh shared RE once;
3. audit and conditionally refresh each spec's requirement and evidence memory;
4. audit and conditionally rebuild each missing or stale per-spec graph;
5. continue after a bounded member failure;
6. build and atomically write one candidate from persisted member graph bytes;
7. audit that exact candidate, write the audit, and return its exit code.

- [ ] **Step 4: Implement view and export semantics**

Defaults:

- viewer:
  `.echelon/runtime/graph/workspace.html`;
- viewer lens: `exceptions` when findings exist, otherwise `portfolio`;
- export: DOT to stdout unless `--output` is supplied.

A valid graph is rendered even for `fail` or `unavailable`, followed by the
audit exit code. Missing/invalid persisted graph returns `2` without output.

- [ ] **Step 5: Run CLI and integration tests**

Run:

```bash
python -m pytest -q \
  tests/unit/test_cli_graph.py \
  tests/unit/test_cli_workspace_graph.py \
  tests/integration/test_spec_graph_workflow.py
```

- [ ] **Step 6: Commit Task 4 using graph-only CLI hunks**

`src/echelon/cli_app.py` may contain unrelated work. Stage only the
workspace-graph registration and command hunks:

```bash
git add tests/unit/test_cli_workspace_graph.py tests/unit/test_cli_graph.py
git add src/echelon/workspace_graph_refresh.py tests/unit/test_workspace_graph_refresh.py
git add -p src/echelon/cli_app.py
git diff --cached --check
git commit -m "Add workspace graph commands"
```

---

### Task 5: Documentation And Real-Workspace Verification

**Files:**
- Modify: `README.md`
- Modify:
  `docs/superpowers/specs/2026-07-30-workspace-artifact-graph-design.md`
- Create: `tests/integration/test_workspace_graph_workflow.py`

**Interfaces:**
- Documents and verifies the complete operator sequence from healthy per-spec
  graphs through workspace composition and viewing.

- [ ] **Step 1: Add an end-to-end synthetic integration test**

Create two canonical specs with persisted healthy graphs and assert:

```python
build = runner.invoke(app, ["graph", "workspace", "refresh", "--write"])
view = runner.invoke(app, ["graph", "workspace", "view", "--no-open"])
export = runner.invoke(
    app,
    ["graph", "workspace", "export", "--format", "dot", "--output", "workspace.dot"],
)
assert build.exit_code == view.exit_code == export.exit_code == 0
```

Then change one member graph and assert workspace audit fails with that spec as
the subject while view/export still produce output.

- [ ] **Step 2: Document the workspace layer**

Extend the README artifact graph workflow with:

```bash
echelon graph refresh <spec> --write
echelon graph workspace refresh --write
echelon graph workspace view
```

Explain that workspace refresh repairs stale memory and member graphs through
their existing pipelines before composition, while the other workspace
commands only inspect or compose current persisted state.

- [ ] **Step 3: Run the complete focused regression matrix**

Run:

```bash
python -m pytest -q \
  tests/unit/test_workspace_graph.py \
  tests/unit/test_workspace_graph_audit.py \
  tests/unit/test_workspace_graph_visualization.py \
  tests/unit/test_graph_visualization.py \
  tests/unit/test_cli_graph.py \
  tests/unit/test_cli_workspace_graph.py \
  tests/unit/test_spec_graph.py \
  tests/unit/test_spec_graph_audit.py \
  tests/integration/test_spec_graph_workflow.py \
  tests/integration/test_workspace_graph_workflow.py
```

- [ ] **Step 4: Verify packaging and browser behavior**

Build a wheel and verify the existing Cytoscape asset remains packaged. Generate
a healthy synthetic workspace viewer and inspect:

- desktop viewport;
- 390x844 mobile viewport;
- `portfolio`, `exceptions`, `memory`, and `delivery` lens switching;
- search and selection;
- nonblank canvas;
- no horizontal overflow or browser console errors.

- [ ] **Step 5: Smoke-test real workspace refresh**

Run in both `/Users/michalbachorik/work/md_distribution` and
`/Users/michalbachorik/work/optasearch`:

```bash
echelon graph workspace refresh --write
echelon graph workspace view --no-open
echelon graph workspace export --format dot --output /tmp/workspace-graph.dot
dot -Tsvg /tmp/workspace-graph.dot -o /tmp/workspace-graph.svg
```

Record which memory domains and per-spec graphs were skipped as current or
refreshed as stale, plus healthy, excluded, and unavailable member counts.
Verify a second refresh is a no-op for upstream state and that each exit code
matches the workspace audit.

- [ ] **Step 6: Run final diff and artifact checks**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Confirm generated runtime files, build output, and unrelated working-tree
changes are not staged.

- [ ] **Step 7: Commit documentation and integration verification**

```bash
git add \
  README.md \
  docs/superpowers/specs/2026-07-30-workspace-artifact-graph-design.md \
  tests/integration/test_workspace_graph_workflow.py
git commit -m "Document and verify workspace graph workflow"
```

---

### Task 6: Final Review

**Files:**
- Review all workspace graph implementation files and staged commits.

**Interfaces:**
- Produces: a verified, review-ready workspace graph implementation on `main`.

- [ ] **Step 1: Review against every design section**

Check authority, discovery, member classification, identity, freshness,
partial-state behavior, CLI, visualization, and deferred-scope boundaries.

- [ ] **Step 2: Review for accidental duplicate work**

Confirm the implementation:

- does not parse requirement/task/evidence/RE content during composition;
- does not call per-spec builders;
- does not mine memory;
- does not use per-spec audit sidecars as authority;
- does not add a graph database or semantic inference.

- [ ] **Step 3: Run the focused matrix once more from the committed tree**

Use the Task 5 matrix and require zero failures. Record unavailable tooling
explicitly rather than claiming it ran.

- [ ] **Step 4: Inspect commit and worktree boundaries**

Run:

```bash
git log --oneline --decorate -8
git status --short
git show --stat --oneline HEAD
```

Verify unrelated pre-existing changes remain untouched and unstaged.
