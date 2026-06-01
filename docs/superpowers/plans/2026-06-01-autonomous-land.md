# Autonomous Land Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `echelon land <spec_id>` autonomously prepare, verify, push, and land completed feature branches while stopping only for semantic conflicts.

**Architecture:** Keep `harness.land.land()` as the public entry point, but split branch preparation and conflict resolution into focused helpers. Add an options/result model so CLI flags and auto-land can use the same behavior without branching into separate code paths.

**Tech Stack:** Python 3.11, git CLI via existing `harness.gitops._run_git`, pytest, existing Echelon terminal banners.

---

## File Structure

- Modify `src/harness/land.py`: add `LandOptions`, `LandPrepareResult`, preparation flow, conflict helpers, and improved `land()` orchestration.
- Modify `src/harness/gitops.py`: add small query/push helpers only if needed; keep complex land logic out of GitOps.
- Modify `src/echelon/cli.py`: parse `echelon land` flags and pass `LandOptions`.
- Modify `src/harness/skills/run_skill.py`: keep auto-land using default autonomous behavior.
- Modify `tests/unit/test_land.py`: add temporary-git-repo integration tests for branch preparation, conflict autoresolution, and clean failure.
- Modify `tests/unit/test_land_cli.py`: add CLI flag wiring tests.

## Task 1: Add Land Options and Result Models

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing tests for default options and backwards compatibility**

Add to `tests/unit/test_land.py`:

```python
from harness.land import LandOptions, LandPrepareResult


@pytest.mark.unit
class TestLandOptions:
    def test_default_land_options_are_autonomous_merge(self) -> None:
        options = LandOptions()
        assert options.autoresolve is True
        assert options.prepare_only is False
        assert options.continue_existing is False
        assert options.strategy == "merge"

    def test_prepare_result_records_conflict_state(self) -> None:
        result = LandPrepareResult(
            status="blocked",
            branch="001-feature",
            prepared_commit=None,
            pushed=False,
            conflicted_files=["src/app.py"],
            autoresolved_files=[".gitignore"],
            message="semantic conflicts remain",
        )
        assert result.status == "blocked"
        assert result.conflicted_files == ["src/app.py"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'LandOptions' -q
```

Expected: import failure because `LandOptions` and `LandPrepareResult` do not exist.

- [ ] **Step 3: Add minimal dataclasses**

In `src/harness/land.py`, after imports:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LandOptions:
    autoresolve: bool = True
    prepare_only: bool = False
    continue_existing: bool = False
    strategy: str = "merge"


@dataclass(frozen=True)
class LandPrepareResult:
    status: str
    branch: str
    prepared_commit: str | None = None
    pushed: bool = False
    conflicted_files: list[str] = field(default_factory=list)
    autoresolved_files: list[str] = field(default_factory=list)
    message: str = ""
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'LandOptions' -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: add land option models"
```

## Task 2: Wire CLI Land Flags

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_land_cli.py`

- [ ] **Step 1: Write failing CLI flag tests**

Add to `tests/unit/test_land_cli.py`:

```python
@patch("harness.land.land")
@patch("harness.gitops.GitOpsManager")
@patch("harness.config.load_config")
def test_land_passes_continue_option(
    self, mock_load_config, mock_gitops_cls, mock_land
):
    from echelon.cli import _cmd_land

    mock_load_config.return_value = MagicMock()
    mock_gitops_cls.return_value = MagicMock()
    mock_land.return_value = True

    with pytest.raises(SystemExit) as exc_info:
        _cmd_land(["042", "--continue"])

    assert exc_info.value.code == 0
    options = mock_land.call_args.kwargs["options"]
    assert options.continue_existing is True


@patch("harness.land.land")
@patch("harness.gitops.GitOpsManager")
@patch("harness.config.load_config")
def test_land_passes_prepare_only_and_no_autoresolve(
    self, mock_load_config, mock_gitops_cls, mock_land
):
    from echelon.cli import _cmd_land

    mock_load_config.return_value = MagicMock()
    mock_gitops_cls.return_value = MagicMock()
    mock_land.return_value = True

    with pytest.raises(SystemExit):
        _cmd_land(["042", "--prepare-only", "--no-autoresolve"])

    options = mock_land.call_args.kwargs["options"]
    assert options.prepare_only is True
    assert options.autoresolve is False


@patch("harness.land.land")
@patch("harness.gitops.GitOpsManager")
@patch("harness.config.load_config")
def test_land_passes_rebase_strategy(
    self, mock_load_config, mock_gitops_cls, mock_land
):
    from echelon.cli import _cmd_land

    mock_load_config.return_value = MagicMock()
    mock_gitops_cls.return_value = MagicMock()
    mock_land.return_value = True

    with pytest.raises(SystemExit):
        _cmd_land(["042", "--strategy", "rebase"])

    assert mock_land.call_args.kwargs["options"].strategy == "rebase"
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land_cli.py -k 'option or strategy' -q
```

Expected: tests fail because `_cmd_land` does not parse or pass `options`.

- [ ] **Step 3: Parse flags in `_cmd_land`**

In `src/echelon/cli.py`, update `_cmd_land` help text and parse arguments:

```python
    from harness.land import LandOptions, land

    spec_id = args[0]
    continue_existing = "--continue" in args[1:]
    prepare_only = "--prepare-only" in args[1:]
    autoresolve = "--no-autoresolve" not in args[1:]
    strategy = "merge"
    if "--strategy" in args[1:]:
        idx = args.index("--strategy")
        try:
            strategy = args[idx + 1]
        except IndexError:
            print("✗ --strategy requires 'merge' or 'rebase'", file=sys.stderr)
            sys.exit(1)
    if strategy not in {"merge", "rebase"}:
        print("✗ --strategy must be 'merge' or 'rebase'", file=sys.stderr)
        sys.exit(1)
    options = LandOptions(
        autoresolve=autoresolve,
        prepare_only=prepare_only,
        continue_existing=continue_existing,
        strategy=strategy,
    )
```

Change the `land()` call to:

```python
    success = land(spec_id, project_dir=project_dir, gitops=gitops, options=options)
```

- [ ] **Step 4: Update existing CLI assertion**

In `tests/unit/test_land_cli.py`, update `test_calls_land_with_correct_args` to include default options:

```python
        options = mock_land.call_args.kwargs["options"]
        assert options.autoresolve is True
        assert options.prepare_only is False
        assert options.continue_existing is False
        assert options.strategy == "merge"
```

- [ ] **Step 5: Run CLI tests and verify GREEN**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land_cli.py -q
```

Expected: all `test_land_cli.py` tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/echelon/cli.py tests/unit/test_land_cli.py
git commit -m "feat: add autonomous land CLI flags"
```

## Task 3: Add Branch Preparation Helper

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Add temporary git helpers to tests**

Append these helpers near the bottom of `tests/unit/test_land.py` before new integration tests:

```python
def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")


def _commit(path: Path, rel: str, text: str, message: str) -> str:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(path, "add", rel)
    _git(path, "commit", "-m", message)
    return _git(path, "rev-parse", "HEAD").stdout.strip()
```

- [ ] **Step 2: Write failing preparation success test**

Add:

```python
@pytest.mark.unit
def test_prepare_feature_branch_merges_default_and_pushes(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature work")
    _git(repo, "checkout", "main")
    _commit(repo, "main.txt", "main\n", "main work")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "prepared"
    assert result.branch == "001-feature"
    assert result.pushed is False
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-feature"
    assert _git(repo, "merge-base", "--is-ancestor", "main", "001-feature", check=False).returncode == 0
```

- [ ] **Step 3: Run test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'prepare_feature_branch_merges_default' -q
```

Expected: import failure for `prepare_feature_branch`.

- [ ] **Step 4: Implement minimal merge preparation**

In `src/harness/land.py`, import `_run_git`:

```python
from harness.gitops import _run_git
```

Add:

```python
def prepare_feature_branch(
    *,
    spec_id: str,
    feature_branch: str,
    project_dir: Path,
    gitops: Any,
    options: LandOptions,
) -> LandPrepareResult:
    default_branch = gitops.get_default_branch()
    _run_git(["checkout", feature_branch], cwd=str(project_dir))
    if options.strategy != "merge":
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            message="rebase strategy is not implemented yet",
        )
    result = _run_git(
        ["merge", "--no-ff", default_branch, "-m", f"Merge {default_branch} into {feature_branch}"],
        cwd=str(project_dir),
        check=False,
    )
    if result.returncode == 0:
        commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
        return LandPrepareResult(
            status="prepared",
            branch=feature_branch,
            prepared_commit=commit,
            pushed=False,
        )
    conflicted = _list_unmerged_files(project_dir)
    return LandPrepareResult(
        status="blocked",
        branch=feature_branch,
        conflicted_files=conflicted,
        message="merge conflicts remain",
    )


def _list_unmerged_files(project_dir: Path) -> list[str]:
    result = _run_git(
        ["diff", "--name-only", "--diff-filter=U"],
        cwd=str(project_dir),
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
```

- [ ] **Step 5: Run test and verify GREEN**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'prepare_feature_branch_merges_default' -q
```

Expected: test passes.

- [ ] **Step 6: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: prepare feature branch before landing"
```

## Task 4: Auto-Resolve `.gitignore` Add/Add Conflicts

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing `.gitignore` union test**

Add:

```python
@pytest.mark.unit
def test_prepare_feature_branch_autoresolves_gitignore_union(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, ".gitignore", "runs/\n.build/\n", "feature ignore")
    _git(repo, "checkout", "main")
    _commit(repo, ".gitignore", ".DS_Store\n.claude/\n", "main ignore")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "prepared"
    assert ".gitignore" in result.autoresolved_files
    text = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "runs/" in text
    assert ".build/" in text
    assert ".DS_Store" in text
    assert ".claude/" in text
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'gitignore_union' -q
```

Expected: blocked result or unmerged `.gitignore`.

- [ ] **Step 3: Implement `.gitignore` resolver**

Add helpers:

```python
def _try_autoresolve_conflicts(project_dir: Path, conflicted: list[str]) -> list[str]:
    resolved: list[str] = []
    if ".gitignore" in conflicted and _resolve_gitignore_union(project_dir):
        resolved.append(".gitignore")
    return resolved


def _resolve_gitignore_union(project_dir: Path) -> bool:
    ours = _run_git(["show", ":2:.gitignore"], cwd=str(project_dir), check=False)
    theirs = _run_git(["show", ":3:.gitignore"], cwd=str(project_dir), check=False)
    if ours.returncode != 0 or theirs.returncode != 0:
        return False
    lines: list[str] = []
    seen: set[str] = set()
    for raw in [*ours.stdout.splitlines(), *theirs.stdout.splitlines()]:
        line = raw.rstrip()
        key = line.strip()
        if not key:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    (project_dir / ".gitignore").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    _run_git(["add", ".gitignore"], cwd=str(project_dir))
    return True
```

Update `prepare_feature_branch()` conflict branch:

```python
    conflicted = _list_unmerged_files(project_dir)
    autoresolved = _try_autoresolve_conflicts(project_dir, conflicted) if options.autoresolve else []
    remaining = _list_unmerged_files(project_dir)
    if not remaining:
        _run_git(["commit", "--no-edit"], cwd=str(project_dir))
        commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
        return LandPrepareResult(
            status="prepared",
            branch=feature_branch,
            prepared_commit=commit,
            pushed=False,
            autoresolved_files=autoresolved,
        )
    return LandPrepareResult(
        status="blocked",
        branch=feature_branch,
        conflicted_files=remaining,
        autoresolved_files=autoresolved,
        message="merge conflicts remain",
    )
```

- [ ] **Step 4: Run test and verify GREEN**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'gitignore_union' -q
```

Expected: test passes.

- [ ] **Step 5: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: autoresolve gitignore land conflicts"
```

## Task 5: Stop Safely for Semantic Conflicts

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing semantic conflict test**

Add:

```python
@pytest.mark.unit
def test_prepare_feature_branch_blocks_on_source_conflict(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "src/app.swift", "let value = 1\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "src/app.swift", "let value = 2\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "src/app.swift", "let value = 3\n", "main")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "blocked"
    assert result.conflicted_files == ["src/app.swift"]
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-feature"
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == "src/app.swift"
```

- [ ] **Step 2: Run test and verify current behavior**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'source_conflict' -q
```

Expected: pass if Task 3 already leaves semantic conflicts blocked. If it fails, adjust `prepare_feature_branch()` so it does not abort or checkout `main` after feature-branch conflicts.

- [ ] **Step 3: Add user-facing blocked banner**

In `land()`, when preparation returns `status == "blocked"`, print:

```python
_banner(
    "LAND — FEATURE BRANCH NEEDS CONFLICT RESOLUTION",
    [
        ("spec", spec_id),
        ("branch", feature_branch),
        ("conflicts", "\n".join(prepare_result.conflicted_files)),
        ("next step", f"resolve conflicts, then run: echelon land {spec_id} --continue"),
    ],
    subtitle="Echelon stopped on semantic conflicts.",
)
```

- [ ] **Step 4: Run land tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -q
```

Expected: all `test_land.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: stop land safely on semantic conflicts"
```

## Task 6: Integrate Preparation into `land()`

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing integration test for direct merge after preparation**

Add:

```python
@pytest.mark.unit
def test_land_prepares_feature_branch_before_direct_merge(tmp_path: Path) -> None:
    from harness.land import LandOptions, land

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "main.txt", "main\n", "main")

    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    gitops.get_default_branch.return_value = "main"
    gitops.merge_pr.return_value = False
    gitops.delete_remote_branch.return_value = True
    gitops.merge_branch_into_default.side_effect = lambda branch, project_dir: (
        _git(Path(project_dir), "checkout", "main"),
        _git(Path(project_dir), "merge", "--no-ff", branch, "-m", "land feature"),
        True,
    )[-1]

    result = land("001", project_dir=repo, gitops=gitops, options=LandOptions())

    assert result is True
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "feature\n"
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'prepares_feature_branch_before_direct_merge' -q
```

Expected: fails because `land()` does not call preparation before direct merge.

- [ ] **Step 3: Change `land()` signature and call preparation**

Change signature:

```python
def land(
    spec_id: str,
    *,
    project_dir: Path,
    gitops: Any,
    state_dir: Optional[Path] = None,
    options: Optional[LandOptions] = None,
) -> bool:
    options = options or LandOptions()
```

Before direct merge, call:

```python
        prepare_result = prepare_feature_branch(
            spec_id=spec_id,
            feature_branch=feature_branch,
            project_dir=project_dir,
            gitops=gitops,
            options=options,
        )
        if prepare_result.status == "blocked":
            _banner(...)
            return False
        if options.prepare_only:
            _banner("LAND — PREPARED", [...])
            return True
```

Keep existing PR-merge behavior first, but if PR merge returns `False`, fall through to preparation instead of immediately returning `False`.

- [ ] **Step 4: Update old mock tests**

Existing tests with `MagicMock` gitops need:

```python
gitops.get_default_branch.return_value = "main"
gitops.merge_branch_into_default.return_value = True
```

For tests that only exercise PR path, no preparation should be called if PR merge succeeds.

- [ ] **Step 5: Run land tests and verify GREEN**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -q
```

Expected: all `test_land.py` tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: prepare branches during land"
```

## Task 7: Add Push After Preparation

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing push test**

Add:

```python
@pytest.mark.unit
def test_prepare_feature_branch_pushes_after_success(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "main.txt", "main\n", "main")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"
    gitops.push_prepared_branch.return_value = None

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "prepared"
    gitops.push_prepared_branch.assert_called_once_with(
        str(repo), "001-feature", force_with_lease=False
    )
    assert result.pushed is True
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'pushes_after_success' -q
```

Expected: `push_prepared_branch` is not called.

- [ ] **Step 3: Add GitOps push helper**

In `src/harness/gitops.py`:

```python
    def push_prepared_branch(
        self,
        project_dir: str,
        branch: str,
        *,
        force_with_lease: bool = False,
    ) -> None:
        args = ["push", "origin", branch]
        if force_with_lease:
            args.insert(1, "--force-with-lease")
        _run_git(args, cwd=project_dir)
```

In `prepare_feature_branch()`, after successful merge commit:

```python
        force = options.strategy == "rebase"
        gitops.push_prepared_branch(str(project_dir), feature_branch, force_with_lease=force)
```

Set `pushed=True` in returned result.

- [ ] **Step 4: Run focused and GitOps tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'pushes_after_success' -q
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_gitops_worktree.py tests/unit/test_land.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/gitops.py src/harness/land.py tests/unit/test_land.py
git commit -m "feat: push prepared land branch"
```

## Task 8: Implement `--continue`

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing continue test**

Add:

```python
@pytest.mark.unit
def test_land_continue_commits_resolved_merge(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "src/app.swift", "let value = 1\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "src/app.swift", "let value = 2\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "src/app.swift", "let value = 3\n", "main")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"
    prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )
    (repo / "src/app.swift").write_text("let value = 4\n", encoding="utf-8")
    _git(repo, "add", "src/app.swift")

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(continue_existing=True),
    )

    assert result.status == "prepared"
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    assert "Merge" in _git(repo, "log", "-1", "--format=%s").stdout
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'continue_commits_resolved_merge' -q
```

Expected: continue path not implemented.

- [ ] **Step 3: Implement continue branch**

At the top of `prepare_feature_branch()`:

```python
    if options.continue_existing:
        _run_git(["checkout", feature_branch], cwd=str(project_dir))
        remaining = _list_unmerged_files(project_dir)
        if remaining:
            return LandPrepareResult(
                status="blocked",
                branch=feature_branch,
                conflicted_files=remaining,
                message="conflicts remain",
            )
        merge_head = project_dir / ".git" / "MERGE_HEAD"
        if merge_head.exists():
            _run_git(["commit", "--no-edit"], cwd=str(project_dir))
        commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
        gitops.push_prepared_branch(str(project_dir), feature_branch, force_with_lease=False)
        return LandPrepareResult(
            status="prepared",
            branch=feature_branch,
            prepared_commit=commit,
            pushed=True,
        )
```

- [ ] **Step 4: Run continue test and verify GREEN**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'continue_commits_resolved_merge' -q
```

Expected: test passes.

- [ ] **Step 5: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: continue land after conflict resolution"
```

## Task 9: Verification Gate Before Final Merge

**Files:**
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing verification failure test**

Add:

```python
@pytest.mark.unit
def test_land_blocks_when_verify_command_fails(tmp_path: Path) -> None:
    from harness.land import LandOptions, land

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")

    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    gitops.get_default_branch.return_value = "main"
    gitops.push_prepared_branch.return_value = None
    gitops.merge_branch_into_default.return_value = True
    gitops._config.verify_command = "false"

    result = land("001", project_dir=repo, gitops=gitops, options=LandOptions())

    assert result is False
    gitops.merge_branch_into_default.assert_not_called()
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k 'verify_command_fails' -q
```

Expected: land proceeds without verification or crashes on mock config.

- [ ] **Step 3: Add verification helper**

In `src/harness/land.py`:

```python
def _run_land_verify(project_dir: Path, gitops: Any) -> tuple[bool, str]:
    config = getattr(gitops, "_config", None)
    command = getattr(config, "verify_command", "") if config is not None else ""
    if not command:
        return True, "no verify_command configured"
    result = subprocess.run(
        command.split(),
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output[-2000:]
```

After preparation and before direct/PR merge retry:

```python
        ok, verify_output = _run_land_verify(project_dir, gitops)
        if not ok:
            _banner("LAND — VERIFY FAILED", [...])
            return False
```

- [ ] **Step 4: Run verification test and full land tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -q
```

Expected: all `test_land.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: verify prepared branch before landing"
```

## Task 10: Final Regression Suite and Documentation Update

**Files:**
- Modify: `docs/superpowers/specs/2026-06-01-autonomous-land-design.md` only if implementation deliberately differs from the approved design.

- [ ] **Step 1: Run focused land suite**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py tests/unit/test_land_cli.py tests/unit/test_run_skill.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full unit suite**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit
```

Expected: all unit tests pass.

- [ ] **Step 3: Run whitespace and status checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors. Only intentional files are modified.

- [ ] **Step 4: Commit final polish if needed**

If docs or small cleanup changed:

```bash
git add <changed-files>
git commit -m "test: cover autonomous land flow"
```

If no changes remain, do not create an empty commit.

## Self-Review Notes

- Spec coverage: PR preference, direct merge preparation, `.gitignore` autoresolution, semantic conflict blocking, `--continue`, verify gate, push behavior, and idempotence are covered by tasks.
- Intentional deferral: `.gitattributes`, runtime artifact dropping beyond `.DS_Store`, package-lock regeneration, and rebase implementation are described in the design but should follow after the core merge/autoresolve path is stable. The CLI accepts `--strategy rebase` only after a later task implements it; until then, return a blocked result for rebase.
- No force-push appears in the merge-default path.
