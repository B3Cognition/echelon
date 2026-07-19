# Spec Catalog Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic `echelon spec publish <id>` and `echelon spec publish --all` commands that commit spec-only snapshots from canonical local Phase A branches to the local default branch while retaining every source branch.

**Architecture:** A focused `echelon.spec_publish` service owns local-ref discovery, committed-tree extraction, worktree safety, exact snapshot replacement, provenance, rollback, and commit creation. The Typer front door validates the mutually exclusive command forms and renders structured results; the existing wiki model optionally reads and displays publication provenance.

**Tech Stack:** Python 3.11+, standard library (`dataclasses`, `io`, `json`, `pathlib`, `re`, `shutil`, `subprocess`, `tarfile`, `tempfile`), existing Echelon Git/config/commit-message helpers, Typer, pytest, real temporary Git repositories.

## Global Constraints

- Enhancement tracking is GitHub issue `#166`.
- Inspect only `refs/heads/`; never fetch or inspect remote-tracking refs.
- A canonical branch is `<NNN>-<slug>` with at least three digits and a normalized lowercase alphanumeric/hyphen slug.
- Publish only the committed `specs/<branch-name>/` tree from each selected branch.
- Never merge implementation history or publish `runs/`, `re/`, source code, or other branch paths.
- Never fetch, push, stash, delete, reset, rebase, or otherwise mutate a source branch.
- Create at most one local default-branch commit per invocation.
- Refuse dirty selected spec worktrees and any dirty checked-out default-branch worktree.
- `--all` is atomic; one invalid source aborts every publication.
- Add deterministic `.echelon-publication.json` provenance without a timestamp.
- Unchanged republication is a successful no-op.
- Replace selected destination directories exactly and roll back only publication-owned paths on failure.
- Preserve current branch and caller worktree state.
- CLI help must explicitly distinguish spec-only publication from branch merging and remote operations.

---

## File structure

- `src/echelon/spec_publish.py`: immutable result types, canonical local-branch discovery, identity resolution, Git worktree parsing, committed-tree extraction, validation, exact publication, rollback, and commit creation.
- `src/echelon/cli_app.py`: `echelon spec publish` Typer command, argument contract, help, errors, and result presentation.
- `src/echelon/wiki/model.py`: optional `publication_branch` and `publication_commit` fields on `WikiSpec`.
- `src/echelon/wiki/discovery.py`: safe parser for `.echelon-publication.json`.
- `src/echelon/wiki/render.py`: publication provenance on spec overview pages.
- `tests/unit/test_spec_publish.py`: real-Git service and safety tests.
- `tests/unit/test_cli_spec_publish.py`: command parsing, help, output, and errors.
- `tests/unit/test_wiki_discovery.py`: provenance discovery and malformed-manifest warning.
- `tests/unit/test_wiki_render.py`: provenance rendering.
- `tests/unit/test_cli_typer_app.py`: top-level spec command help contract if the command inventory assertion requires it.
- `README.md`: publication workflow and command table.
- `CHANGELOG.md`: `#166` enhancement entry.

### Task 1: Canonical local branch discovery and identity resolution

**Files:**
- Create: `src/echelon/spec_publish.py`
- Create: `tests/unit/test_spec_publish.py`

**Interfaces:**
- Consumes: `echelon.git_helpers.run_git`, `echelon.phase_a_git.resolve_phase_a_default_branch`.
- Produces: `SpecPublishError`, `SpecPublicationSource`, `discover_publication_sources(project_root, default_branch)`, and `resolve_publication_sources(project_root, identity, publish_all, default_branch)`.

- [ ] **Step 1: Write failing discovery tests**

Create real-Git helpers and tests with this behavior:

```python
def test_discovery_uses_only_canonical_local_branches(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    create_spec_branch(repo, "001-first", "# First\n")
    create_spec_branch(repo, "002-second", "# Second\n")
    git(repo, "branch", "backup/003-third")
    git(repo, "branch", "codex/004-fourth")
    git(repo, "update-ref", "refs/remotes/origin/005-remote", "HEAD")
    git(repo, "branch", "006-missing-spec")

    sources = discover_publication_sources(repo, "main")

    assert [source.spec_id for source in sources] == ["001-first", "002-second"]
    assert all(source.branch == source.spec_id for source in sources)


def test_numeric_resolution_rejects_ambiguous_canonical_branches(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    create_spec_branch(repo, "003-first", "# First\n")
    create_spec_branch(repo, "003-second", "# Second\n")

    with pytest.raises(SpecPublishError, match="ambiguous.*003-first.*003-second"):
        resolve_publication_sources(
            repo, identity="003", publish_all=False, default_branch="main"
        )
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_spec_publish.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'echelon.spec_publish'`.

- [ ] **Step 3: Implement immutable source types and canonical discovery**

Implement these public contracts:

```python
CANONICAL_SPEC_BRANCH_RE = re.compile(
    r"^(?P<number>\d{3,})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)$"
)


class SpecPublishError(RuntimeError):
    """Raised when spec catalog publication cannot proceed safely."""


@dataclass(frozen=True)
class SpecPublicationSource:
    spec_id: str
    spec_number: str
    branch: str
    commit: str
    source_path: str


def discover_publication_sources(
    project_root: Path,
    default_branch: str,
) -> tuple[SpecPublicationSource, ...]:
    """Return sorted canonical local branches with matching committed spec.md."""


def resolve_publication_sources(
    project_root: Path,
    *,
    identity: str | None,
    publish_all: bool,
    default_branch: str,
) -> tuple[SpecPublicationSource, ...]:
    """Resolve exactly one command form and reject identity ambiguity."""
```

Use `git for-each-ref --format=%(refname:short)%00%(objectname) refs/heads` and
`git cat-file -e <branch>:specs/<branch>/spec.md`. Exclude `default_branch` before
matching. For `--all`, reject duplicate `spec_number` values even though both
branches otherwise match the canonical shape. For a full identity, require exact
branch-name equality; for numeric input, normalize with `int()` and compare the
numeric prefix.

- [ ] **Step 4: Run discovery tests and verify green**

Run the Task 1 test file. Expected: all discovery and resolution tests pass.

- [ ] **Step 5: Commit discovery**

```bash
git add src/echelon/spec_publish.py tests/unit/test_spec_publish.py
git commit -m "feat: discover publishable spec branches (#166)"
```

### Task 2: Atomic spec-only publication and provenance

**Files:**
- Modify: `src/echelon/spec_publish.py`
- Modify: `tests/unit/test_spec_publish.py`

**Interfaces:**
- Consumes: Task 1 `SpecPublicationSource`, existing `build_echelon_commit_message`, `EchelonCommitMetadata`, `get_full_resolved_config`, and `resolve_phase_a_default_branch`.
- Produces: `PublishedSpec`, `SpecPublishResult`, and `publish_specs(project_root, identity=None, publish_all=False)`.

- [ ] **Step 1: Write failing publication tests**

Add tests that publish from committed source trees while `main` is checked out:

```python
def test_publish_one_copies_only_matching_committed_spec_and_retains_branch(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    source_commit = create_spec_branch(
        repo,
        "001-first",
        "# First\n",
        extra_files={
            "specs/001-first/plan.md": "# Plan\n",
            "src/implementation.py": "do_not_publish = True\n",
        },
    )
    source_ref_before = git(repo, "rev-parse", "refs/heads/001-first")
    git(repo, "switch", "main")

    result = publish_specs(repo, identity="001")

    assert result.created_commit is True
    assert result.default_branch == "main"
    assert result.published[0].source_commit == source_commit
    assert (repo / "specs/001-first/spec.md").read_text() == "# First\n"
    assert not (repo / "src/implementation.py").exists()
    manifest = json.loads(
        (repo / "specs/001-first/.echelon-publication.json").read_text()
    )
    assert manifest == {
        "schema_version": 1,
        "source_branch": "001-first",
        "source_commit": source_commit,
        "spec_id": "001-first",
    }
    assert git(repo, "rev-parse", "refs/heads/001-first") == source_ref_before


def test_publish_all_is_one_commit_and_republish_is_noop(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    create_spec_branch(repo, "001-first", "# First\n")
    create_spec_branch(repo, "002-second", "# Second\n")
    git(repo, "switch", "main")
    before = git(repo, "rev-list", "--count", "main")

    first = publish_specs(repo, publish_all=True)
    second = publish_specs(repo, publish_all=True)

    assert int(git(repo, "rev-list", "--count", "main")) == int(before) + 1
    assert first.created_commit is True
    assert second.created_commit is False
    assert second.default_commit == first.default_commit
```

Add an exact-replacement test in which `main` contains a stale destination file
that the source commit removed; after republishing, the stale file must not exist.
Add a destination-collision test where `main` contains `specs/001-old/` and the
selected branch is `001-new`; publication must fail before mutation.

- [ ] **Step 2: Run the new tests and verify behavioral failures**

Expected: imports succeed but `publish_specs`, `PublishedSpec`, and
`SpecPublishResult` are missing.

- [ ] **Step 3: Implement staging, provenance, replacement, commit, and no-op**

Add these immutable types and entry point:

```python
@dataclass(frozen=True)
class PublishedSpec:
    spec_id: str
    source_branch: str
    source_commit: str
    changed: bool


@dataclass(frozen=True)
class SpecPublishResult:
    default_branch: str
    previous_default_commit: str
    default_commit: str
    created_commit: bool
    destination_worktree: Path
    caller_on_default: bool
    published: tuple[PublishedSpec, ...]


def publish_specs(
    project_root: Path,
    *,
    identity: str | None = None,
    publish_all: bool = False,
) -> SpecPublishResult:
    """Publish committed canonical spec snapshots in one local default commit."""
```

Resolve `target_default_branch` through `get_full_resolved_config` and
`resolve_phase_a_default_branch`. Extract each committed subtree with
`git archive --format=tar <commit> -- specs/<spec-id>` into a staging directory.
Validate every tar member is a regular file or directory inside the requested
spec root; reject links and traversal. Write sorted, newline-terminated provenance.

Before mutation, detect same-number destination directories on the default
worktree. Back up each selected destination into staging, replace it exactly,
stage with `git add -A -- <paths>`, and assert every cached diff path is inside an
allowed selected directory. If the cached diff is empty, unstage and return a
no-op result. Otherwise commit with:

```python
message = build_echelon_commit_message(
    f"docs: publish specs {', '.join(source.spec_id for source in sources)}",
    EchelonCommitMetadata(
        origin="workspace",
        action="spec-publish",
        spec_id=",".join(source.spec_id for source in sources),
    ),
)
```

Return the exact post-commit SHA and per-spec `changed` values computed from the
staged diff.

- [ ] **Step 4: Run publication tests and verify green**

Run Task 1 and Task 2 tests. Expected: all pass and `git status --short` remains
empty in every successful/no-op fixture.

- [ ] **Step 5: Commit atomic publication**

```bash
git add src/echelon/spec_publish.py tests/unit/test_spec_publish.py
git commit -m "feat: publish spec snapshots atomically (#166)"
```

### Task 3: Worktree safety, rollback, and concurrent-ref protection

**Files:**
- Modify: `src/echelon/spec_publish.py`
- Modify: `tests/unit/test_spec_publish.py`

**Interfaces:**
- Consumes: Task 2 `publish_specs` transaction and `SpecPublishResult`.
- Produces: internal `GitWorktree`, `_list_worktrees`, `_publication_worktree`, `_validate_source_worktrees`, and `_rollback_destinations` helpers.

- [ ] **Step 1: Write failing real-worktree safety tests**

Add these cases:

```python
def test_publish_refuses_dirty_selected_spec_in_linked_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    create_spec_branch(repo, "001-first", "# Committed\n")
    linked = tmp_path / "first-worktree"
    git(repo, "worktree", "add", str(linked), "001-first")
    (linked / "specs/001-first/spec.md").write_text("# Dirty\n")

    with pytest.raises(SpecPublishError, match="001-first.*uncommitted"):
        publish_specs(repo, identity="001")


def test_publish_from_spec_branch_uses_temporary_default_worktree(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    create_spec_branch(repo, "001-first", "# First\n")
    git(repo, "switch", "001-first")
    caller_head = git(repo, "rev-parse", "HEAD")

    result = publish_specs(repo, identity="001")

    assert git(repo, "branch", "--show-current") == "001-first"
    assert git(repo, "rev-parse", "HEAD") == caller_head
    assert result.destination_worktree != repo
    assert not result.destination_worktree.exists()
    assert git(repo, "show", "main:specs/001-first/spec.md") == "# First"
```

Also test:

- a clean secondary `main` worktree is used;
- a dirty secondary `main` worktree is refused;
- unrelated dirty files in a source worktree do not block publication;
- a monkeypatched commit failure restores existing destinations and removes new
  destinations while leaving unrelated paths unchanged; and
- moving `refs/heads/main` after staging but before commit produces a concurrent
  change error and rolls back publication-owned paths.

- [ ] **Step 2: Run worktree tests and verify failures**

Expected: source-dirty/default-worktree/temp-worktree/rollback assertions fail
because Task 2 handles only the caller's current default worktree.

- [ ] **Step 3: Implement worktree parsing and transactional rollback**

Use this internal model:

```python
@dataclass(frozen=True)
class GitWorktree:
    path: Path
    branch: str | None


@contextmanager
def _publication_worktree(
    project_root: Path,
    default_branch: str,
) -> Iterator[tuple[Path, bool]]:
    """Yield a clean checked-out default worktree or a removable temporary one."""
```

Parse `git worktree list --porcelain`; strip `refs/heads/` from `branch` records.
For every selected checked-out source branch, call `git status --porcelain --
specs/<id>` in that worktree and refuse nonempty output. Find a checked-out
default worktree and require a completely empty `git status --porcelain`; if none
exists, create `<tempdir>/default` with `git worktree add <path> <default_branch>`
and remove/prune it in `finally`.

Capture the default SHA before staging and compare `refs/heads/<default>` again
immediately before `git commit`. For rollback, remove each mutated destination,
copy back its staged backup when it existed, and run
`git reset <captured-sha> -- <selected-paths>` to restore the index only. Verify
the default worktree is clean after rollback; if not, include its status in the
raised `SpecPublishError`.

- [ ] **Step 4: Run all service tests and verify green**

Run `tests/unit/test_spec_publish.py -q`. Expected: all branch, transaction,
worktree, concurrency, no-op, and rollback tests pass.

- [ ] **Step 5: Commit safety behavior**

```bash
git add src/echelon/spec_publish.py tests/unit/test_spec_publish.py
git commit -m "feat: safeguard spec catalog publication (#166)"
```

### Task 4: Typer command and explicit CLI help

**Files:**
- Modify: `src/echelon/cli_app.py`
- Create: `tests/unit/test_cli_spec_publish.py`
- Modify: `tests/unit/test_cli_typer_app.py` if required by its command inventory contract.

**Interfaces:**
- Consumes: `publish_specs`, `SpecPublishError`, and `SpecPublishResult` from Tasks 1–3.
- Produces: `echelon spec publish [SPEC_OR_ID] [--all]`.

- [ ] **Step 1: Write failing CLI and help tests**

```python
def test_publish_help_explains_spec_only_local_behavior() -> None:
    result = CliRunner().invoke(app, ["spec", "publish", "--help"])

    assert result.exit_code == 0
    assert "committed spec snapshots" in result.output
    assert "does not merge implementation history" in result.output
    assert "local branches only" in result.output
    assert "does not fetch, push, or delete" in result.output
    assert "--all" in result.output


@pytest.mark.parametrize("args", [["spec", "publish"], ["spec", "publish", "003", "--all"]])
def test_publish_requires_exactly_one_command_form(args: list[str]) -> None:
    result = CliRunner().invoke(app, args)

    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_publish_success_reports_commit_retained_branches_and_no_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("echelon.spec_publish.publish_specs", lambda *_args, **_kwargs: result_fixture())

    result = CliRunner().invoke(app, ["spec", "publish", "003"])

    assert result.exit_code == 0
    assert "003-add-feature-opta-search" in result.output
    assert "Source branches retained" in result.output
    assert "Nothing was pushed" in result.output
    assert "git push origin main" in result.output
    assert "echelon wiki build" in result.output
```

- [ ] **Step 2: Run CLI tests and verify missing-command failures**

Expected: Typer reports `No such command 'publish'` and the help assertions fail.

- [ ] **Step 3: Implement the command and presentation**

Add `publish` to `spec_app` common forms and implement:

```python
@spec_app.command("publish")
def spec_publish(
    spec_or_id: Optional[str] = typer.Argument(
        None,
        help="Canonical local spec branch name or unique numeric ID.",
    ),
    publish_all: bool = typer.Option(
        False,
        "--all",
        help="Publish every canonical local spec branch in one commit.",
    ),
) -> None:
    """Publish committed spec snapshots to the local default branch.

    Copies only matching specs/<id>/ trees. This does not merge implementation
    history and does not fetch, push, delete, or modify source branches.
    """
```

Validate `(spec_or_id is None) == publish_all` and raise
`typer.BadParameter("choose exactly one spec identity or --all")`. Catch
`SpecPublishError`, print its message with the `Spec publish failed:` prefix to
stderr, and exit 1.
Render stable one-line entries for every source, the default commit/no-op state,
retained-branch/no-push notices, and context-aware switch/push/wiki next steps.

- [ ] **Step 4: Run CLI, service, and Typer contract tests**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_cli_spec_publish.py \
  tests/unit/test_spec_publish.py \
  tests/unit/test_cli_typer_app.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit CLI behavior**

```bash
git add src/echelon/cli_app.py tests/unit/test_cli_spec_publish.py tests/unit/test_cli_typer_app.py
git commit -m "feat: expose spec catalog publication commands (#166)"
```

### Task 5: Wiki provenance, documentation, and final verification

**Files:**
- Modify: `src/echelon/wiki/model.py`
- Modify: `src/echelon/wiki/discovery.py`
- Modify: `src/echelon/wiki/render.py`
- Modify: `tests/unit/test_wiki_discovery.py`
- Modify: `tests/unit/test_wiki_render.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `.echelon-publication.json` schema version 1 from Task 2.
- Produces: optional wiki publication provenance and user-facing workflow documentation.

- [ ] **Step 1: Write failing wiki provenance tests**

```python
def test_discovery_reads_spec_publication_provenance(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "specs/003-search")
    (spec / ".echelon-publication.json").write_text(json.dumps({
        "schema_version": 1,
        "spec_id": "003-search",
        "source_branch": "003-search",
        "source_commit": "a" * 40,
    }))

    model = discover_wiki_model(tmp_path, generated_at="2026-07-19T10:00:00Z")

    assert model.specs[0].publication_branch == "003-search"
    assert model.specs[0].publication_commit == "a" * 40


def test_spec_overview_displays_publication_provenance(tmp_path: Path) -> None:
    project_root, model = workspace_with_published_spec(tmp_path)

    render_wiki(model, project_root, tmp_path / "out")

    overview = (tmp_path / "out/Specs/003-search/Overview.md").read_text()
    assert "Published from branch: `003-search`" in overview
    assert "Source commit: `aaaaaaaaaaaa`" in overview
```

Add a malformed/mismatched manifest test that leaves both fields `None` and adds
an `invalid-spec-publication` warning naming the manifest path.

- [ ] **Step 2: Run wiki tests and verify missing-field failures**

Expected: `WikiSpec` has no `publication_branch` or `publication_commit`, and the
overview lacks provenance.

- [ ] **Step 3: Implement safe provenance parsing and rendering**

Append backward-compatible defaults to `WikiSpec`:

```python
publication_branch: str | None = None
publication_commit: str | None = None
```

Parse only schema 1 dictionaries whose `spec_id` matches the directory, whose
`source_branch` equals that same canonical ID, and whose `source_commit` is a
40- to 64-character lowercase hexadecimal string. Invalid input becomes a
warning with this exact payload:

```python
WikiWarning(
    "invalid-spec-publication",
    "Publication manifest is invalid or does not match its spec directory.",
    manifest_path,
)
```

Invalid provenance never aborts wiki generation. Add a `Publication Provenance`
section to `_spec_overview` only when both fields are present.

- [ ] **Step 4: Update README and changelog**

Add this workflow near the human artifact wiki section:

```bash
echelon spec publish 003  # spec-only snapshot commit on local main
echelon spec publish --all
git push origin main      # explicit; publish never pushes
git switch main
echelon wiki build
```

State that source branches are retained and no implementation history is merged.
Add the three command forms and safety summary to the command table. Add an
Unreleased `#166` enhancement entry to `CHANGELOG.md` explaining why Echelon
publishes snapshots instead of making the wiki branch-aware.

- [ ] **Step 5: Run focused verification**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_spec_publish.py \
  tests/unit/test_cli_spec_publish.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_phase_a_git.py \
  tests/unit/test_spec_switch.py \
  tests/unit/test_spec_switch_cli.py \
  tests/unit/test_wiki_discovery.py \
  tests/unit/test_wiki_render.py \
  tests/unit/test_wiki_service.py \
  tests/performance/test_wiki_build_performance.py -q
bash scripts/bash/dry-run.sh
```

Expected: focused pytest suite passes; dry run reports zero failures.

- [ ] **Step 6: Run the full regression suite**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest
```

Expected: no failures beyond the accepted baseline cases:

- `test_blocked_non_escalation_run_does_not_claim_ready_to_build`
- four failing `tests/unit/test_spec_depends_gate.py` dependency-gate cases

- [ ] **Step 7: Commit integration and documentation**

```bash
git add src/echelon/wiki/model.py src/echelon/wiki/discovery.py \
  src/echelon/wiki/render.py tests/unit/test_wiki_discovery.py \
  tests/unit/test_wiki_render.py README.md CHANGELOG.md
git commit -m "docs: integrate spec catalog publication (#166)"
```
