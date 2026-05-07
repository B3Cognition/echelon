# `echelon land` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `echelon land <spec-id>` — an idempotent command that merges the feature branch PR, deletes the remote feature branch and local `harness/*` branches, cleans up harness worktrees, and marks the spec as landed in its frontmatter; and wire it to fire automatically after harness convergence.

**Architecture:** Three layers land on top of each other: (C) `land()` core function in `src/harness/land.py` is the idempotent primitive; (A) `run_skill.py` calls it automatically when the harness converges; (B) `land()` writes `status: landed` to the spec's YAML frontmatter for light speckit ecosystem integration. A new `echelon land <spec-id>` CLI command exposes (C) for manual/recovery use. A separate skill edit (Task 6) fixes `echelon bugfix` to create a missing branch via `speckit.git.feature` instead of erroring.

**Layered ownership (explicit boundary):**
- **spec-kit git extension** owns: branch creation, naming/numbering, auto-commit of spec artifacts, branch validation
- **echelon gitops** owns: worktree isolation, push/PR lifecycle, PR merge, branch deletion, cleanup (`echelon land`)
- They hand off at the feature branch: spec-kit creates it, echelon builds on it and lands it

**Tech Stack:** Python 3.12, pytest, `unittest.mock`, PyYAML (already used by `spec_frontmatter.py`), `subprocess` (already used by `gitops.py`), `gh`/`glab` CLI (already used by `merge_pr`).

**Spec-kit availability:** Treat as given — echelon only operates in spec-kit-managed projects. The git extension is installed by default with spec-kit. No need to guard against its absence.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `src/harness/land.py` | `land()`, `find_pr_url()`, `_cleanup_worktrees()`, `_delete_harness_branches()` |
| **Create** | `tests/unit/test_land.py` | All tests for land.py |
| **Modify** | `src/harness/spec_frontmatter.py` | Add `write_status(spec_dir, status)` |
| **Modify** | `src/harness/gitops.py` | Add `delete_remote_branch(branch_name, *, project_dir)` |
| **Modify** | `src/echelon/cli.py` | Add top-level `echelon land <spec-id>` command |
| **Modify** | `src/harness/skills/run_skill.py` | Replace `attempt_auto_merge` with `land()` call after convergence |
| **Modify** | `src/harness/run_intent.py` | Change `auto_merge` default to `True` |
| **Modify** | `extension/commands/echelon.bugfix.md` | Create branch via `speckit.git.feature` if missing (instead of erroring) |
| **Modify** | `tests/unit/test_spec_frontmatter.py` | Add `TestWriteStatus` class |
| **Create** | `tests/unit/test_land_gitops.py` | Tests for `delete_remote_branch` |

---

## Task 1: `write_status` in `spec_frontmatter.py`

**Files:**
- Modify: `src/harness/spec_frontmatter.py` (add after `write_targets`, lines 46–71)
- Modify: `tests/unit/test_spec_frontmatter.py` (add `TestWriteStatus` class)

- [ ] **Step 1.1: Write failing tests**

Add to `tests/unit/test_spec_frontmatter.py`:

```python
from harness.spec_frontmatter import read_frontmatter, write_status, write_targets


@pytest.mark.unit
class TestWriteStatus:
    def test_adds_status_field(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets: []\n---\n# Body\n")
        write_status(spec_dir, "landed")
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_creates_frontmatter_when_absent(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# No frontmatter\n")
        write_status(spec_dir, "landed")
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_overwrites_existing_status(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\nstatus: running\n---\n# Body\n")
        write_status(spec_dir, "landed")
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_preserves_other_frontmatter_keys(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - repo-a\n---\n# Body\n")
        write_status(spec_dir, "landed")
        fm = read_frontmatter(spec_dir)
        assert fm["targets"] == ["repo-a"]
        assert fm["status"] == "landed"

    def test_returns_modified_file_path(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\n---\n")
        result = write_status(spec_dir, "landed")
        assert result == spec_dir / "spec.md"

    def test_raises_when_no_md_file(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "specs" / "042-empty"
        empty_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            write_status(empty_dir, "landed")
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd /Users/michalbachorik/work/evolution/echelon
.venv/bin/python -m pytest tests/unit/test_spec_frontmatter.py::TestWriteStatus -v
```

Expected: `ImportError` or `AttributeError` — `write_status` not yet defined.

- [ ] **Step 1.3: Implement `write_status`**

In `src/harness/spec_frontmatter.py`, add after line 71 (after `write_targets`):

```python
def write_status(spec_dir: Path, status: str) -> Path:
    """Write (or replace) the ``status:`` field in spec_dir's frontmatter.

    Creates a frontmatter block if none exists. Returns the modified file path.
    Preserves all other frontmatter keys.
    """
    md = _find_spec_md(spec_dir)
    if md is None:
        raise FileNotFoundError(f"No .md file found in {spec_dir}")

    text = md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    try:
        data: Dict[str, Any] = yaml.safe_load(m.group(1)) if m else {}
        data = data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        logger.warning("write_status: corrupt YAML frontmatter in %s — dropping existing keys", md)
        data = {}

    data["status"] = status
    front = yaml.dump(data, default_flow_style=False, sort_keys=False,
                      allow_unicode=True).rstrip()
    md.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
    return md
```

- [ ] **Step 1.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_spec_frontmatter.py::TestWriteStatus -v
```

Expected: 6 passed.

- [ ] **Step 1.5: Commit**

```bash
git add src/harness/spec_frontmatter.py tests/unit/test_spec_frontmatter.py
git commit -m "feat(land): add write_status to spec_frontmatter"
```

---

## Task 2: `delete_remote_branch` in `gitops.py`

**Files:**
- Modify: `src/harness/gitops.py` (add method to `GitOpsManager`, immediately after `merge_pr`)
- Create: `tests/unit/test_land_gitops.py`

- [ ] **Step 2.1: Confirm the subprocess pattern used by `merge_pr`**

```bash
grep -n "def merge_pr" src/harness/gitops.py
sed -n '<merge_pr start line>,+30p' src/harness/gitops.py
```

Confirm `merge_pr` uses `subprocess.run([...], capture_output=True, text=True, timeout=60, check=True)`. The new method follows the identical pattern.

- [ ] **Step 2.2: Write failing tests**

Create `tests/unit/test_land_gitops.py`:

```python
"""Tests for GitOpsManager.delete_remote_branch."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from harness.gitops import GitOpsManager


def _make_gitops() -> MagicMock:
    """Return a GitOpsManager mock with delete_remote_branch bound as a real method."""
    m = MagicMock(spec=GitOpsManager)
    m.delete_remote_branch = GitOpsManager.delete_remote_branch.__get__(m, GitOpsManager)
    return m


@pytest.mark.unit
class TestDeleteRemoteBranch:
    def test_calls_git_push_delete(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path)
            )
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "push", "origin", "--delete", "042-my-feature"]

    def test_uses_project_dir_as_cwd(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gitops.delete_remote_branch("042-my-feature", project_dir=str(tmp_path))
        kwargs = mock_run.call_args[1]
        assert kwargs["cwd"] == str(tmp_path)

    def test_returns_false_on_git_error(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(128, "git")
            result = gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path)
            )
        assert result is False

    def test_returns_false_on_timeout(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 60)
            result = gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path)
            )
        assert result is False

    def test_accepts_custom_remote(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path), remote="upstream"
            )
        cmd = mock_run.call_args[0][0]
        assert cmd[2] == "upstream"
```

> **Note:** If the `_make_gitops()` mock construction fails, read the first 40 lines of `tests/unit/test_gitops_skill.py` to see how that test file constructs a `GitOpsManager`, then replicate that pattern here.

- [ ] **Step 2.3: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_land_gitops.py -v
```

Expected: `AttributeError` — `delete_remote_branch` not yet on `GitOpsManager`.

- [ ] **Step 2.4: Implement `delete_remote_branch`**

In `src/harness/gitops.py`, add immediately after the `merge_pr` method:

```python
def delete_remote_branch(
    self, branch_name: str, *, project_dir: str, remote: str = "origin"
) -> bool:
    """Delete branch_name from remote. Returns True if deleted, False if blocked or not found."""
    try:
        subprocess.run(
            ["git", "push", remote, "--delete", branch_name],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
            cwd=project_dir,
        )
        logger.info("Deleted remote branch %s/%s", remote, branch_name)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("Could not delete remote branch %s/%s: %s", remote, branch_name, e)
        return False
```

- [ ] **Step 2.5: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_land_gitops.py -v
```

Expected: 5 passed.

- [ ] **Step 2.6: Commit**

```bash
git add src/harness/gitops.py tests/unit/test_land_gitops.py
git commit -m "feat(land): add delete_remote_branch to GitOpsManager"
```

---

## Task 3: `land.py` core module

**Files:**
- Create: `src/harness/land.py`
- Create: `tests/unit/test_land.py`

`_cleanup_worktrees` removes worktree directories under `.specify/harness/worktrees/{spec_id}/`. `_delete_harness_branches` deletes local `harness/{spec_id}/*` branches that accumulated from legacy harness runs.

- [ ] **Step 3.1: Write failing tests**

Create `tests/unit/test_land.py`:

```python
"""Tests for harness.land — idempotent spec completion."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from harness.land import find_pr_url, land


def _write_state(state_dir: Path, spec_id: str, strategy: str, pr_url: str | None) -> None:
    d = state_dir / spec_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{strategy}.json").write_text(
        json.dumps({"spec_id": spec_id, "pr_url": pr_url}), encoding="utf-8"
    )


def _make_gitops(
    feature_branch: str | None = "042-my-feature",
    merge_result: bool = True,
    delete_result: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.find_feature_branch.return_value = feature_branch
    m.merge_pr.return_value = merge_result
    m.delete_remote_branch.return_value = delete_result
    return m


@pytest.mark.unit
class TestFindPrUrl:
    def test_returns_url_from_state_file(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "042", "default", "https://github.com/o/r/pull/7")
        assert find_pr_url("042", tmp_path) == "https://github.com/o/r/pull/7"

    def test_returns_none_when_spec_dir_missing(self, tmp_path: Path) -> None:
        assert find_pr_url("042", tmp_path) is None

    def test_returns_none_when_all_files_lack_pr_url(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "042", "default", None)
        assert find_pr_url("042", tmp_path) is None

    def test_skips_corrupt_json(self, tmp_path: Path) -> None:
        d = tmp_path / "042"
        d.mkdir()
        (d / "bad.json").write_text("{not json}", encoding="utf-8")
        _write_state(tmp_path, "042", "good", "https://github.com/o/r/pull/9")
        assert find_pr_url("042", tmp_path) == "https://github.com/o/r/pull/9"


@pytest.mark.unit
class TestLand:
    def test_returns_true_when_feature_branch_not_found(self, tmp_path: Path) -> None:
        gitops = _make_gitops(feature_branch=None)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_not_called()
        gitops.delete_remote_branch.assert_not_called()

    def test_merges_pr_when_feature_branch_and_pr_url_exist(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".specify" / "harness" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/7")

    def test_deletes_remote_branch_after_merge(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".specify" / "harness" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        gitops.delete_remote_branch.assert_called_once_with(
            "042-my-feature", project_dir=str(tmp_path)
        )

    def test_returns_false_when_merge_blocked(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".specify" / "harness" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops(merge_result=False)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is False
        gitops.delete_remote_branch.assert_not_called()

    def test_skips_merge_when_no_pr_url(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_not_called()
        gitops.delete_remote_branch.assert_called_once()

    def test_calls_ensure_on_default_branch(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        gitops.ensure_on_default_branch.assert_called_once_with(str(tmp_path))

    def test_writes_landed_status_to_spec_frontmatter(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("---\ntargets: []\n---\n# Spec\n", encoding="utf-8")
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_is_idempotent_when_branch_already_deleted(self, tmp_path: Path) -> None:
        gitops = _make_gitops(feature_branch=None)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True

    def test_cleans_up_worktrees(self, tmp_path: Path) -> None:
        worktree_dir = (
            tmp_path / ".specify" / "harness" / "worktrees" / "042" / "default" / "iter-0"
        )
        worktree_dir.mkdir(parents=True)
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        gitops.destroy_worktree.assert_called_once_with(worktree_dir, keep_branch=True)

    def test_deletes_legacy_harness_branches(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            # Simulate: git branch lists two harness/* branches for spec 042
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="  harness/042/codegen/iter-0\n  harness/042/codegen/iter-1\n",
            )
            land("042", project_dir=tmp_path, gitops=gitops)
        # Both harness branches should have been deleted
        delete_calls = [c for c in mock_run.call_args_list if "--delete" in str(c) or "-D" in str(c)]
        assert len(delete_calls) == 2

    def test_accepts_explicit_state_dir(self, tmp_path: Path) -> None:
        custom_state = tmp_path / "custom-state"
        _write_state(custom_state, "042", "default", "https://github.com/o/r/pull/9")
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops, state_dir=custom_state)
        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/9")
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_land.py -v
```

Expected: `ModuleNotFoundError` — `harness.land` does not exist yet.

- [ ] **Step 3.3: Implement `land.py`**

Create `src/harness/land.py`:

```python
"""Land — idempotent spec completion: merge PR, delete branch, clean worktrees, mark done."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def find_pr_url(spec_id: str, state_dir: Path) -> Optional[str]:
    """Return the first PR URL found in any strategy state file for spec_id."""
    spec_state_dir = state_dir / spec_id
    if not spec_state_dir.exists():
        return None
    for state_file in sorted(spec_state_dir.glob("*.json")):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("pr_url"):
                return data["pr_url"]
        except (json.JSONDecodeError, OSError):
            continue
    return None


def land(
    spec_id: str,
    *,
    project_dir: Path,
    gitops: Any,
    state_dir: Optional[Path] = None,
) -> bool:
    """Idempotent: merge PR, delete remote branch, clean worktrees, mark spec landed.

    Returns True if spec is now in landed state.
    Returns False only when PR merge is blocked — caller must retry or merge manually.
    """
    if state_dir is None:
        state_dir = project_dir / ".specify" / "harness" / "state"

    feature_branch = gitops.find_feature_branch(spec_id)
    if feature_branch is None:
        logger.info("land: %s — feature branch not found, already landed", spec_id)
        _cleanup_worktrees(spec_id, project_dir, gitops)
        _delete_harness_branches(spec_id, project_dir)
        return True

    pr_url = find_pr_url(spec_id, state_dir)
    if pr_url:
        merged = gitops.merge_pr(pr_url)
        if not merged:
            logger.warning(
                "land: %s — PR merge blocked; branch protection requires manual merge", spec_id
            )
            return False
    else:
        logger.warning("land: %s — no PR URL in state, skipping merge step", spec_id)

    gitops.delete_remote_branch(feature_branch, project_dir=str(project_dir))
    _cleanup_worktrees(spec_id, project_dir, gitops)
    _delete_harness_branches(spec_id, project_dir)
    gitops.ensure_on_default_branch(str(project_dir))

    from harness.spec_frontmatter import find_spec_dir, write_status

    spec_dir = find_spec_dir(spec_id, project_dir)
    if spec_dir:
        write_status(spec_dir, "landed")

    logger.info("land: %s — landed successfully", spec_id)
    return True


def _cleanup_worktrees(spec_id: str, project_dir: Path, gitops: Any) -> None:
    worktree_base = project_dir / ".specify" / "harness" / "worktrees" / spec_id
    if not worktree_base.exists():
        return
    for strategy_dir in sorted(worktree_base.iterdir()):
        if not strategy_dir.is_dir():
            continue
        for iter_dir in sorted(strategy_dir.iterdir()):
            if iter_dir.is_dir():
                try:
                    gitops.destroy_worktree(iter_dir, keep_branch=True)
                    logger.info("land: removed worktree %s", iter_dir)
                except Exception as e:  # noqa: BLE001
                    logger.warning("land: could not remove worktree %s: %s", iter_dir, e)


def _delete_harness_branches(spec_id: str, project_dir: Path) -> None:
    """Delete local harness/{spec_id}/* branches left over from legacy harness runs."""
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"harness/{spec_id}/*"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_dir),
        )
        branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]
        for branch in branches:
            try:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                    cwd=str(project_dir),
                )
                logger.info("land: deleted legacy branch %s", branch)
            except subprocess.CalledProcessError as e:
                logger.warning("land: could not delete legacy branch %s: %s", branch, e)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("land: could not list harness branches for %s: %s", spec_id, e)
```

- [ ] **Step 3.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_land.py -v
```

Expected: 11 passed.

- [ ] **Step 3.5: Run the full unit suite to check for regressions**

```bash
.venv/bin/python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: all existing tests still pass.

- [ ] **Step 3.6: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat(land): add land() core module with harness branch cleanup"
```

---

## Task 4: `echelon land <spec-id>` CLI command

**Files:**
- Modify: `src/echelon/cli.py`

- [ ] **Step 4.1: Read the routing block in `main()`**

```bash
sed -n '540,606p' src/echelon/cli.py
```

Confirm the `if/elif subcmd ==` block structure used to dispatch commands.

- [ ] **Step 4.2: Add `_cmd_land` function**

In `src/echelon/cli.py`, add this function after `_cmd_spec` (or near the other `_cmd_*` functions):

```python
def _cmd_land(args: list[str]) -> None:
    """echelon land <spec-id> — merge, clean up, and mark spec as landed."""
    if not args or args[0] in ("-h", "--help"):
        print("Usage: echelon land <spec-id>")
        print("  Merge the PR, delete the feature branch, clean up legacy harness")
        print("  branches and worktrees, and mark the spec as landed. Idempotent.")
        return

    spec_id = args[0]
    base_dir = str(Path.cwd())

    from harness.config import load_config
    from harness.gitops import GitOpsManager
    from harness.land import land

    config = load_config(base_dir=base_dir)
    gitops = GitOpsManager(config=config)

    success = land(spec_id, project_dir=Path(base_dir), gitops=gitops)
    if success:
        print(f"  {spec_id} landed.", file=sys.stderr)
    else:
        print(
            f"  {spec_id}: merge blocked — check PR for branch protection requirements.",
            file=sys.stderr,
        )
        sys.exit(1)
```

- [ ] **Step 4.3: Wire into `main()` routing**

In the `main()` routing block, add `land` before the `else` branch:

```python
elif subcmd == "land":
    _cmd_land(args)
```

- [ ] **Step 4.4: Smoke test the CLI wiring**

```bash
python -m echelon.cli land --help
```

Expected output:
```
Usage: echelon land <spec-id>
  Merge the PR, delete the feature branch, clean up legacy harness
  branches and worktrees, and mark the spec as landed. Idempotent.
```

- [ ] **Step 4.5: Run CLI tests to check for regressions**

```bash
.venv/bin/python -m pytest tests/unit/test_cli_harness_run.py -v
```

Expected: all pass.

- [ ] **Step 4.6: Commit**

```bash
git add src/echelon/cli.py
git commit -m "feat(land): add echelon land CLI command"
```

---

## Task 5: Auto-land after harness convergence

**Files:**
- Modify: `src/harness/skills/run_skill.py` (lines 175–179)
- Modify: `src/harness/run_intent.py` (line 37: `auto_merge` default)

- [ ] **Step 5.1: Read the current auto-merge section and RunIntent default**

```bash
sed -n '170,180p' src/harness/skills/run_skill.py
grep -n "auto_merge" src/harness/run_intent.py | head -10
```

Confirm:
- `run_skill.py:175–179`: `if intent.auto_merge and len(results) == 1: merged = attempt_auto_merge(...)`
- `run_intent.py:37`: `auto_merge: bool = False`

- [ ] **Step 5.2: Check which tests assert `auto_merge=False` as default**

```bash
grep -rn "auto_merge" tests/unit/test_run_intent.py tests/unit/test_merge.py
```

Note any tests that construct `RunIntent` without `auto_merge` and assert on merge-skipping behaviour — these will need `auto_merge=False` added explicitly.

- [ ] **Step 5.3: Replace `attempt_auto_merge` with `land()` in `run_skill.py`**

Replace lines 175–179 in `src/harness/skills/run_skill.py`:

```python
    # 8. Auto-land if applicable (merge PR + delete branch + cleanup)
    if intent.auto_merge and len(results) == 1 and results[0].status == "converged":
        from harness.land import land

        landed = land(intent.spec_id, project_dir=Path(base_dir), gitops=gitops)
        if landed:
            print("  Landed successfully!", file=sys.stderr)
        else:
            print(
                "  Auto-land blocked — branch protection requires manual merge.",
                file=sys.stderr,
            )
```

Remove the now-unused import at the top of `run_skill.py`:

```python
from harness.merge import attempt_auto_merge  # DELETE THIS LINE
```

Verify it's gone:

```bash
grep -n "attempt_auto_merge" src/harness/skills/run_skill.py
```

Expected: no output.

- [ ] **Step 5.4: Change `auto_merge` default to `True` in `run_intent.py`**

In `src/harness/run_intent.py` line 37, change:

```python
auto_merge: bool = False
```

to:

```python
auto_merge: bool = True
```

- [ ] **Step 5.5: Fix tests broken by the default change**

```bash
.venv/bin/python -m pytest tests/unit/test_run_intent.py tests/unit/test_merge.py -v 2>&1 | grep FAILED
```

For each failing test, add `auto_merge=False` explicitly to the `RunIntent(...)` constructor call. Example:

```python
# Before:
intent = RunIntent(spec_id="001", mode="banzai", strategies=["default"])
# After:
intent = RunIntent(spec_id="001", mode="banzai", strategies=["default"], auto_merge=False)
```

- [ ] **Step 5.6: Run full unit suite**

```bash
.venv/bin/python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -40
```

Expected: all pass.

- [ ] **Step 5.7: Commit**

```bash
git add src/harness/skills/run_skill.py src/harness/run_intent.py tests/unit/test_run_intent.py tests/unit/test_merge.py
git commit -m "feat(land): wire auto-land into harness convergence, default auto_merge=True"
```

---

## Task 6: `echelon bugfix` — create branch if missing

**Files:**
- Modify: `extension/commands/echelon.bugfix.md` (Step 5 branch detection section)

This is a skill edit — no Python, no tests. The change is in the LLM prompt that drives `echelon bugfix`.

- [ ] **Step 6.1: Read the current branch detection section**

```bash
grep -n "FEATURE_BRANCH\|git checkout\|branch not found\|Has echelon" extension/commands/echelon.bugfix.md
```

Locate the exact lines where the skill either switches to the feature branch or errors.

- [ ] **Step 6.2: Replace the error path with branch creation**

Find the section that reads (approximately):

```
git checkout "$FEATURE_BRANCH"
If feature branch does not exist: error — "Feature branch not found. Has echelon.run been completed?"
```

Replace the error path with:

```markdown
If the feature branch `{spec_id}-*` does not exist:
1. Use `speckit.git.feature` (via Skill tool) with the spec name derived from
   `specs/{spec_id}-*/spec.md` title or directory name as the feature description.
   This creates a new branch following spec-kit's naming convention.
2. If `speckit.git.feature` is unavailable, run directly:
   `.specify/extensions/git/scripts/bash/create-new-feature.sh --json --allow-existing-branch --short-name "<spec-name>" "<spec title>"`
3. Confirm the new branch with `git branch --show-current`.
4. Log in reasoning journal: `bugfix: created missing feature branch {branch_name} for spec {spec_id}`.
```

- [ ] **Step 6.3: Smoke test by reading the updated section back**

```bash
grep -n -A 10 "FEATURE_BRANCH\|feature branch" extension/commands/echelon.bugfix.md | head -40
```

Confirm the error path is gone and the creation path is present.

- [ ] **Step 6.4: Commit**

```bash
git add extension/commands/echelon.bugfix.md
git commit -m "feat(land): echelon bugfix creates missing feature branch via speckit.git.feature"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| `echelon land <spec-id>` command | Task 4 |
| Merge PR (echelon gitops owns this) | Task 3 (`land()` calls `gitops.merge_pr`) |
| Delete remote feature branch | Task 2 + Task 3 |
| Delete legacy `harness/*` local branches | Task 3 (`_delete_harness_branches`) |
| Clean up harness worktrees | Task 3 (`_cleanup_worktrees`) |
| Mark spec as landed in frontmatter | Task 1 + Task 3 |
| Idempotent (no-op if already landed) | Task 3 (branch-not-found path) |
| Auto-fire after harness convergence | Task 5 |
| `auto_merge` defaults to `True` | Task 5 |
| bugfix creates branch if missing (spec-kit git owns creation) | Task 6 |
| spec-kit git extension treated as available (given) | No guard code added anywhere |
| Ownership boundary explicit | Architecture section + Task 6 uses `speckit.git.feature` |

**Placeholder scan:** No TBDs. All code blocks complete. Task 6 provides exact fallback command.

**Type consistency:**
- `find_pr_url(spec_id: str, state_dir: Path) -> Optional[str]` — consistent across test and implementation
- `land(spec_id, *, project_dir, gitops, state_dir) -> bool` — consistent
- `delete_remote_branch(branch_name, *, project_dir, remote="origin") -> bool` — called exactly this way in `land()`
- `write_status(spec_dir, status) -> Path` — matches `write_targets` signature in same module
