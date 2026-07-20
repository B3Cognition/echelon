# Default-Branch Wiki Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make wiki build, status, snapshots, and automatic refresh read the configured local default-branch catalog without switching the caller's active branch.

**Architecture:** A focused `echelon.wiki.catalog_source` context manager resolves the local default branch and yields either the caller root or a detached temporary worktree pinned to the catalog commit. The existing service separates that source root from the caller-owned output root, and every freshness operation uses the same resolver.

**Tech Stack:** Python 3.11+, Git worktrees, Typer, pytest, immutable dataclasses, existing Echelon config/Git helpers.

## Global Constraints

- Use local refs only; never fetch, push, stash, or switch the caller branch.
- Keep generated output at `<caller>/.echelon/runtime/wiki/`.
- Honor `.echelon/local.yml` over `.echelon/config.yml`.
- Preserve non-Git and on-default-branch behavior.
- Clean the detached source worktree before atomically publishing a staged vault.
- Keep older valid wiki manifests readable.

---

## File structure

- Create `src/echelon/wiki/catalog_source.py`: default-branch resolution, detached worktree lifecycle, local override propagation, and immutable source metadata.
- Create `tests/unit/test_wiki_catalog_source.py`: real-Git resolver and cleanup contracts.
- Modify `src/echelon/wiki/service.py`: separate catalog source from output root across build, status, snapshots, and refresh.
- Modify `tests/unit/test_wiki_service.py`: reproduce feature-branch publish/build behavior and freshness transitions.
- Modify `src/echelon/cli_app.py`: report indexed catalog provenance and simplify publish-to-wiki guidance.
- Modify `tests/unit/test_cli_wiki.py` and `tests/unit/test_cli_spec_publish.py`: user-facing output contracts.
- Modify `README.md` and `CHANGELOG.md`: document corrected behavior.

### Task 1: Resolve an immutable wiki catalog source

**Files:**
- Create: `src/echelon/wiki/catalog_source.py`
- Create: `tests/unit/test_wiki_catalog_source.py`

**Interfaces:**
- Consumes: `get_full_resolved_config`, `resolve_phase_a_default_branch`, and `run_git`.
- Produces: `WikiCatalogError`, `WikiCatalogSource`, and `wiki_catalog_source(project_root)`.

- [ ] **Step 1: Write failing non-Git, on-default, and cross-branch tests**

Create real Git helpers and these core cases:

```python
def test_non_git_workspace_uses_caller_root(tmp_path: Path) -> None:
    with wiki_catalog_source(tmp_path) as source:
        assert source.workspace_root == tmp_path.resolve()
        assert source.source_root == tmp_path.resolve()
        assert source.branch is None
        assert source.revision is None
        assert source.temporary is False


def test_default_branch_caller_uses_live_workspace(tmp_path: Path) -> None:
    repo = init_repo(tmp_path, branch="master")
    with wiki_catalog_source(repo) as source:
        assert source.source_root == repo.resolve()
        assert source.branch == "master"
        assert source.temporary is False


def test_feature_branch_uses_pinned_temporary_default_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path, branch="master")
    master_commit = git(repo, "rev-parse", "master")
    git(repo, "switch", "-c", "004-feature")
    caller_head = git(repo, "rev-parse", "HEAD")
    with wiki_catalog_source(repo) as source:
        temporary_path = source.source_root
        assert source.branch == "master"
        assert source.revision == master_commit
        assert source.temporary is True
        assert git(source.source_root, "rev-parse", "HEAD") == master_commit
    assert not temporary_path.exists()
    assert git(repo, "branch", "--show-current") == "004-feature"
    assert git(repo, "rev-parse", "HEAD") == caller_head
```

Add a local override case with committed `target_default_branch: main` and local
`target_default_branch: master`. Assert the context resolves `master` and copies
the caller's local override into the temporary source.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_wiki_catalog_source.py -q
```

Expected: collection fails because `echelon.wiki.catalog_source` does not exist.

- [ ] **Step 3: Implement the catalog source context**

Implement this public contract:

```python
@dataclass(frozen=True)
class WikiCatalogSource:
    workspace_root: Path
    source_root: Path
    branch: str | None
    revision: str | None
    dirty: bool
    temporary: bool


class WikiCatalogError(RuntimeError):
    """Raised when a default-branch wiki source cannot be prepared safely."""


@contextmanager
def wiki_catalog_source(project_root: Path) -> Iterator[WikiCatalogSource]:
    """Yield the caller root or a pinned local default-branch worktree."""
```

Resolution steps:

1. Resolve `project_root` and probe `git rev-parse --is-inside-work-tree` with
   `check=False`; yield a non-Git source on failure.
2. Read the merged config and choose `target_default_branch` from the top level,
   falling back to `harness.target_default_branch`.
3. Call `resolve_phase_a_default_branch` and capture its branch/commit.
4. If `git branch --show-current` equals the default, yield the caller root and
   compute dirtiness with checked `git status --porcelain -- specs re`.
5. Otherwise create `tempfile.mkdtemp`, add `<temp>/catalog` with
   `git worktree add --detach --quiet <path> <commit>`, copy the caller's optional
   `.echelon/local.yml`, and yield a temporary source.
6. In `finally`, require successful `git worktree remove --force` and `prune`,
   then remove the temporary parent. On failure, raise `WikiCatalogError` naming
   the retained path.

- [ ] **Step 4: Run catalog-source tests and verify GREEN**

Run the Task 1 test command. Expected: all tests pass and every fixture reports
an empty `git status --short` after the context exits.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/echelon/wiki/catalog_source.py tests/unit/test_wiki_catalog_source.py
git commit -m "fix: resolve default-branch wiki catalog source"
```

### Task 2: Build and assess the vault from the catalog source

**Files:**
- Modify: `src/echelon/wiki/service.py`
- Modify: `tests/unit/test_wiki_service.py`

**Interfaces:**
- Consumes: Task 1 `wiki_catalog_source` and `WikiCatalogSource`.
- Produces: catalog-aware `build_wiki`, `wiki_status`, `capture_input_snapshot`, and `refresh_after_changed_command`.

- [ ] **Step 1: Write the failing reported-sequence integration test**

Add a real-Git fixture that leaves the caller on `004-feature` while another
worktree commits four published specs to `master`:

```python
def test_feature_branch_build_uses_default_catalog_without_switching(tmp_path: Path) -> None:
    repo, caller_head = workspace_with_feature_and_published_master(tmp_path)

    result = build_wiki(repo, now=lambda: FIXED_NOW)

    assert git(repo, "branch", "--show-current") == "004-feature"
    assert git(repo, "rev-parse", "HEAD") == caller_head
    assert result.catalog_branch == "master"
    assert result.catalog_revision == git(repo, "rev-parse", "master")
    for spec_id in ("001-one", "002-two", "003-three", "004-four"):
        assert (result.output_dir / f"Specs/{spec_id}/Overview.md").is_file()
    assert wiki_status(repo).state == "fresh"
```

Also add:

- a default-worktree commit of `005-five` makes status stale from branch 004;
- `capture_input_snapshot` before that commit and
  `refresh_after_changed_command` afterward rebuilds a vault containing 005;
- uncommitted branch-004 spec edits neither appear in the catalog wiki nor make
  its status stale.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_wiki_service.py -q
```

Expected: the new build contains only feature-branch inputs and
`WikiBuildResult` lacks catalog provenance.

- [ ] **Step 3: Separate source and output roots in the service**

Extend the immutable result:

```python
@dataclass(frozen=True)
class WikiBuildResult:
    output_dir: Path
    home_path: Path
    input_count: int
    output_count: int
    warning_count: int
    catalog_branch: str | None
    catalog_revision: str | None
```

Change `_manifest_payload` to accept `WikiCatalogSource` and write:

```python
"catalog_branch": source.branch,
"workspace_revision": source.revision,
"workspace_dirty": source.dirty,
```

In `build_wiki`, keep staging/output under the caller root, but enter
`wiki_catalog_source(root)` for discovery, hashing, and rendering. Normalize the
model for presentation before rendering:

```python
model = replace(
    discover_wiki_model(source.source_root, generated_at=generated_at),
    workspace_name=root.name,
    workspace_root=str(root),
)
inputs = canonical_input_hashes(source.source_root, artifacts=model.artifacts)
render_result = render_wiki(model, source.source_root, staging)
```

Exit the catalog context before `_publish_staging(staging, output)`.

Use the same context in `wiki_status` and `capture_input_snapshot`. In
`refresh_after_changed_command`, compute `after` through
`capture_current_catalog_inputs(project_root)` and call the catalog-aware
`build_wiki` when artifact hashes differ.

- [ ] **Step 4: Run service, discovery, render, and performance tests**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_wiki_catalog_source.py \
  tests/unit/test_wiki_service.py \
  tests/unit/test_wiki_discovery.py \
  tests/unit/test_wiki_render.py \
  tests/performance/test_wiki_build_performance.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/echelon/wiki/service.py tests/unit/test_wiki_service.py
git commit -m "fix: build wiki from default-branch catalog"
```

### Task 3: Correct CLI guidance and documentation

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_wiki.py`
- Modify: `tests/unit/test_cli_spec_publish.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 2 `WikiBuildResult.catalog_branch` and `.catalog_revision`.
- Produces: branch-independent CLI guidance and user documentation.

- [ ] **Step 1: Write failing CLI output tests**

Update the wiki build test to assert:

```python
assert "Catalog: master@" in result.output
```

Replace the spec-publish temporary-worktree next-step expectation with:

```python
assert "Refresh navigation: echelon wiki build" in result.output
assert "git switch" not in result.output
assert "cd " not in result.output
```

Add a service-result fixture when needed so the CLI contract is independent of
the test's current Git branch.

- [ ] **Step 2: Run CLI tests and verify RED**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_cli_wiki.py tests/unit/test_cli_spec_publish.py -q
```

Expected: wiki output lacks catalog provenance and publish output still suggests
switching or changing directory.

- [ ] **Step 3: Implement CLI output**

After the existing input/output summary in `wiki_build`, print:

```python
if result.catalog_branch and result.catalog_revision:
    typer.echo(
        f"Catalog: {result.catalog_branch}@{result.catalog_revision[:12]}"
    )
```

In `spec_publish`, retain push guidance but always print exactly:

```python
typer.echo("Refresh navigation: echelon wiki build")
```

Remove branch-switch and destination-worktree-dependent wiki guidance.

- [ ] **Step 4: Update README and changelog**

Replace the manual `git switch main` wiki workflow with:

```bash
echelon spec publish --all
echelon wiki build        # reads the local default-branch catalog
git push origin master    # explicit; publish never pushes
```

State that build/status/auto-refresh resolve the local configured default branch
without switching the active Phase A branch. Add a `Fixed` changelog entry
describing why feature-branch wiki builds previously omitted published specs.

- [ ] **Step 5: Run focused verification**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_wiki_catalog_source.py \
  tests/unit/test_wiki_service.py \
  tests/unit/test_wiki_discovery.py \
  tests/unit/test_wiki_render.py \
  tests/unit/test_cli_wiki.py \
  tests/unit/test_cli_spec_publish.py \
  tests/unit/test_cli_typer_app.py \
  tests/performance/test_wiki_build_performance.py -q
bash scripts/bash/dry-run.sh
```

Expected: focused tests pass and dry run reports zero failures.

- [ ] **Step 6: Run the regression suite**

Run the full pytest suite. Compare any failures with the established baseline;
the change must introduce no new failures.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/echelon/cli_app.py tests/unit/test_cli_wiki.py \
  tests/unit/test_cli_spec_publish.py README.md CHANGELOG.md
git commit -m "docs: explain default-branch wiki catalog"
```

- [ ] **Step 8: Request independent review and finish the branch**

Review the complete diff against
`docs/superpowers/specs/2026-07-19-wiki-default-branch-catalog-design.md`, fix all
critical/important findings, rerun verification, then use
`superpowers:finishing-a-development-branch` for integration.
