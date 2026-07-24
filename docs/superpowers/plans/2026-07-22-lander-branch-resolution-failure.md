# Lander Branch-Resolution Failure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent mirror fetch or branch-listing failures from being reported as successful, already-completed landings.

**Architecture:** Preserve `find_feature_branch()`'s `str | None` result for successful queries, but propagate `GitOpsError` for lookup failures. Convert that exception into a controlled `False` result at the `land()` orchestration boundary so existing auto-land output correctly reports failure.

**Tech Stack:** Python 3, pytest, `unittest.mock`, existing `GitOpsManager` and landing modules.

## Global Constraints

- Return `None` only after a successful mirror query finds no matching branch.
- Do not perform worktree cleanup, branch deletion, readiness checks, or merge work after branch resolution fails.
- Preserve genuine already-landed and legacy harness-branch behavior.
- Do not modify or include unrelated dirty-worktree files in commits.

---

### Task 1: Propagate Git branch-lookup failures

**Files:**
- Create: `tests/unit/test_gitops_branch_lookup.py`
- Modify: `src/harness/gitops.py:435-469`

**Interfaces:**
- Consumes: `GitOpsManager.fetch_mirror() -> None`, `_run_git(...) -> CompletedProcess`, `GitOpsError`.
- Produces: `GitOpsManager.find_feature_branch(spec_id: str) -> Optional[str]`, where operational failures raise `GitOpsError`.

- [ ] **Step 1: Write failing fetch and listing regression tests**

Create a manager with a temporary mirror, patch `fetch_mirror()` to raise `GitOpsError`, and assert `find_feature_branch()` raises. In a second test, let fetch succeed, patch `_run_git()` to raise `GitOpsError`, and assert it raises:

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.errors import GitOpsError
from harness.gitops import GitOpsManager


def _manager_with_mirror(tmp_path: Path) -> GitOpsManager:
    manager = object.__new__(GitOpsManager)
    manager._mirror_path = tmp_path
    return manager


def test_find_feature_branch_propagates_fetch_failure(tmp_path: Path) -> None:
    manager = _manager_with_mirror(tmp_path)
    error = GitOpsError("fetch failed", command="git fetch --all --prune")
    with patch.object(manager, "fetch_mirror", side_effect=error):
        with pytest.raises(GitOpsError, match="fetch failed"):
            manager.find_feature_branch("042")


def test_find_feature_branch_propagates_branch_listing_failure(tmp_path: Path) -> None:
    manager = _manager_with_mirror(tmp_path)
    error = GitOpsError("list failed", command="git branch --list")
    with (
        patch.object(manager, "fetch_mirror"),
        patch("harness.gitops._run_git", side_effect=error),
    ):
        with pytest.raises(GitOpsError, match="list failed"):
            manager.find_feature_branch("042")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/unit/test_gitops_branch_lookup.py`

Expected: both tests fail because the current implementation swallows the exceptions and returns `None`.

- [ ] **Step 3: Remove exception swallowing from branch lookup**

Change `find_feature_branch()` to call `self.fetch_mirror()` directly and make `_list_branches()` call `_run_git()` directly. Retain branch parsing, matching, and genuine `None` behavior unchanged.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest -q tests/unit/test_gitops_branch_lookup.py`

Expected: `2 passed`.

### Task 2: Block landing after resolution failure

**Files:**
- Modify: `tests/unit/test_land.py`
- Modify: `src/harness/land.py:565-600`

**Interfaces:**
- Consumes: `gitops.find_feature_branch(spec_id)` raising `GitOpsError`.
- Produces: `land(...) -> False` with no destructive cleanup or landing work after the error.

- [ ] **Step 1: Write the failing landing regression test**

Add a test that configures `find_feature_branch()` to raise and asserts the controlled result and absence of cleanup:

```python
from harness.errors import GitOpsError


def test_blocks_when_feature_branch_resolution_fails(self, tmp_path: Path) -> None:
    gitops = _make_gitops()
    gitops.find_feature_branch.side_effect = GitOpsError(
        "mirror fetch failed",
        command="git fetch --all --prune",
    )

    with (
        patch("harness.land._banner") as banner,
        patch("harness.land._cleanup_worktrees") as cleanup,
        patch("harness.land._delete_harness_branches") as delete_branches,
    ):
        result = land("042", project_dir=tmp_path, gitops=gitops)

    assert result is False
    cleanup.assert_not_called()
    delete_branches.assert_not_called()
    assert banner.call_args.args[0] == "LAND — BRANCH RESOLUTION BLOCKED"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest -q tests/unit/test_land.py::TestLand::test_blocks_when_feature_branch_resolution_fails`

Expected: failure from uncaught `GitOpsError`.

- [ ] **Step 3: Add controlled error handling to `land()`**

Wrap only `gitops.find_feature_branch(spec_id)` in `try/except GitOpsError`. On failure, log the error, show the existing `LAND — BRANCH RESOLUTION BLOCKED` banner with an access-repair/retry next step, and return `False` before legacy fallback or cleanup.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest -q tests/unit/test_gitops_branch_lookup.py tests/unit/test_land.py::TestLand::test_blocks_when_feature_branch_resolution_fails tests/unit/test_land.py::TestLand::test_is_idempotent_when_branch_already_deleted tests/unit/test_land.py::TestLand::test_lands_latest_legacy_harness_branch_when_feature_branch_is_missing tests/unit/test_run_skill.py`

Expected: all selected tests pass, including the existing auto-land test that verifies `False` does not produce success output.

### Task 3: Full verification and bounded commit

**Files:**
- Verify only; no additional source files.

**Interfaces:**
- Consumes: completed Tasks 1 and 2.
- Produces: verified and reviewable bug-fix commit.

- [ ] **Step 1: Run complete relevant unit modules**

Run: `pytest -q tests/unit/test_gitops_branch_lookup.py tests/unit/test_land.py tests/unit/test_run_skill.py tests/unit/test_gitops_skill.py`

Expected: all tests pass.

- [ ] **Step 2: Check formatting and exact diff scope**

Run: `git diff --check -- src/harness/gitops.py src/harness/land.py tests/unit/test_gitops_branch_lookup.py tests/unit/test_land.py`

Expected: no output and exit status 0.

Run: `git diff --stat -- src/harness/gitops.py src/harness/land.py tests/unit/test_gitops_branch_lookup.py tests/unit/test_land.py`

Expected: only the four intended implementation/test paths appear.

- [ ] **Step 3: Commit only the fix files**

```bash
git add src/harness/gitops.py src/harness/land.py tests/unit/test_gitops_branch_lookup.py tests/unit/test_land.py
git commit -m "fix: block landing when branch resolution fails" -- src/harness/gitops.py src/harness/land.py tests/unit/test_gitops_branch_lookup.py tests/unit/test_land.py
```

- [ ] **Step 4: Verify commit contents and preserve unrelated changes**

Run: `git show --stat --oneline HEAD && git status --short`

Expected: the fix commit contains only the four intended paths; pre-existing unrelated worktree changes remain present and uncommitted.
