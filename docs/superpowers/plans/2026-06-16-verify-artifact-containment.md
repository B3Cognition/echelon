# Verify Artifact Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dirty verify-owned artifacts explicit in Ralph state and build prompts so COMMANDER no longer has to infer whether modified `fulfillment-report.md` / `fulfillment-gaps.md` files are implementation work or generated verification output.

**Architecture:** Add a pure git-status classifier for verify-owned artifacts, call it from harness context generation, and record the result in state. Keep existing commit/salvage mechanics because `GitOps.commit()` and `_salvage_build_worktree()` already stage all dirty files except `.harness-build-status.json`.

**Tech Stack:** Python harness code, git porcelain parsing, pytest unit tests.

---

## File Structure

- Modify `src/harness/ralph.py`
  - Add `_dirty_verify_artifacts(worktree_path)` helper.
  - Add `_is_verify_owned_artifact(path)` helper.
  - Add `_record_dirty_verify_artifacts(worktree_path, artifacts)` helper.
  - Extend `_with_harness_context()` with a `dirty_verify_artifacts:` block when such files are dirty.
- Modify `tests/unit/test_ralph_outer.py`
  - Add tests for prompt/state labeling of inherited dirty verify artifacts.
  - Add tests that ordinary source dirtiness is not labeled as verify-owned.
- Modify `tests/unit/test_ralph_commit_push.py`
  - Add a regression test that normal commit/push leaves fulfillment artifacts to `gitops.commit`.
- Modify `tests/unit/test_ralph_outer.py`
  - Extend salvage regression to prove fulfillment artifacts are salvaged while `.harness-build-status.json` is excluded.

## Task 1: Label Dirty Verify Artifacts in Harness Context

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [ ] **Step 1: Write failing prompt/state test**

Add this test to `TestHarnessContext` in `tests/unit/test_ralph_outer.py`:

Use a real git repo rooted at `worktree`, not `tmp_path`:

```python
worktree = tmp_path / "worktree"
worktree.mkdir()
subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
spec_dir = worktree / "specs" / "spec-001-demo"
spec_dir.mkdir(parents=True)
(spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
(spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
(spec_dir / "fulfillment-report.md").write_text("old\n", encoding="utf-8")
(worktree / "README.md").write_text("base\n", encoding="utf-8")
subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)
(spec_dir / "fulfillment-report.md").write_text("new\n", encoding="utf-8")
(spec_dir / "fulfillment-gaps.md").write_text("gap\n", encoding="utf-8")

prompt = controller._with_harness_context("body", str(worktree))

assert "dirty_verify_artifacts:" in prompt
assert "specs/spec-001-demo/fulfillment-report.md" in prompt
assert "specs/spec-001-demo/fulfillment-gaps.md" in prompt
assert "Treat these as inherited verify-spec outputs" in prompt
state = state_store.read()
assert state["dirty_verify_artifacts"]["count"] == 2
assert "specs/spec-001-demo/fulfillment-report.md" in state["dirty_verify_artifacts"]["paths"]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage2-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "dirty_verify_owned_artifacts" -q
```

Expected: FAIL because context does not include `dirty_verify_artifacts` and state is not recorded.

- [ ] **Step 3: Implement dirty verify artifact helpers**

Add imports if needed:

```python
from pathlib import PurePosixPath
```

Add helpers near `_with_harness_context()`:

```python
def _dirty_verify_artifacts(self, worktree_path: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    artifacts: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = _porcelain_path(line)
        if path and _is_verify_owned_artifact(path):
            artifacts.append(path)
    return sorted(dict.fromkeys(artifacts))
```

Add module-level helpers near `_git_status_lines()`:

```python
def _porcelain_path(line: str) -> str:
    value = line[3:].strip()
    if " -> " in value:
        value = value.split(" -> ", 1)[1].strip()
    return value.strip('"')

def _is_verify_owned_artifact(path: str) -> bool:
    posix = path.replace("\\", "/")
    if posix.startswith("runs/verify-spec-"):
        return True
    if "/runs/verify-spec-" in posix:
        return True
    if not posix.startswith("specs/"):
        return False
    name = PurePosixPath(posix).name
    return name in {"fulfillment-report.md", "fulfillment-gaps.md"}
```

In `_with_harness_context()`, before building `block`, compute:

```python
dirty_verify_artifacts = self._dirty_verify_artifacts(worktree_path)
dirty_verify_block = ""
if dirty_verify_artifacts:
    self._record_dirty_verify_artifacts(worktree_path, dirty_verify_artifacts)
    dirty_verify_block = (
        "dirty_verify_artifacts:\n"
        + "".join(f"- {path}\n" for path in dirty_verify_artifacts)
        + "Treat these as inherited verify-spec outputs. Do not hand-edit them in build slices; Ralph owns regeneration and commit/salvage.\n"
    )
```

Insert `{dirty_verify_block}` into the Harness Context block after `tasks_file`.

Add:

```python
def _record_dirty_verify_artifacts(self, worktree_path: str, artifacts: list[str]) -> None:
    state = self._state_store.read()
    state["dirty_verify_artifacts"] = {
        "count": len(artifacts),
        "paths": artifacts,
        "worktree": worktree_path,
    }
    self._state_store.write(state)
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage2-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "dirty_verify_owned_artifacts" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "feat: label dirty verify artifacts"
```

## Task 2: Do Not Label Ordinary Source Changes

**Files:**
- Modify: `tests/unit/test_ralph_outer.py`

- [ ] **Step 1: Write regression test**

Add this test near the previous one:

```python
def test_harness_context_does_not_label_source_changes_as_verify_artifacts(self, tmp_path: Path) -> None:
    controller, _provider, _gitops, state_store = _make_controller(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
    spec_dir = worktree / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (worktree / "src").mkdir()
    (worktree / "src" / "feature.swift").write_text("new\n", encoding="utf-8")

    prompt = controller._with_harness_context("body", str(worktree))

    assert "dirty_verify_artifacts:" not in prompt
    assert "dirty_verify_artifacts" not in state_store.read()
```

- [ ] **Step 2: Run test**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage2-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "dirty_verify_artifacts" -q
```

Expected: both dirty verify artifact tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_ralph_outer.py
git commit -m "test: keep source dirtiness out of verify artifact labels"
```

## Task 3: Pin Commit and Salvage Behavior

**Files:**
- Modify: `tests/unit/test_ralph_commit_push.py`
- Modify: `tests/unit/test_ralph_outer.py`

- [ ] **Step 1: Add commit/push regression test**

In `tests/unit/test_ralph_commit_push.py`, add:

```python
def test_commit_and_push_delegates_dirty_verify_artifacts_to_gitops_commit(self, tmp_path):
    ralph, gitops = _make_ralph(tmp_path, spec_id="001-feature")
    worktree_path = str(tmp_path / "worktree")

    with patch("harness.gitops._run_git") as mock_run_git:
        mock_run_git.return_value = MagicMock(stdout="001-feature\n", returncode=0)
        ralph._commit_and_push(worktree_path, outer_iter=0)

    gitops.commit.assert_called_once_with(
        worktree_path,
        "harness: 001-feature/default iter-0",
    )
```

This documents that Ralph does not filter fulfillment artifacts before normal commit; `GitOps.commit()` stages all dirty files.

- [ ] **Step 2: Extend salvage regression**

In `test_build_incomplete_salvages_dirty_worktree_to_commit`, add before invoking the controller:

```python
spec_dir = worktree / "specs" / "spec-001-demo"
spec_dir.mkdir(parents=True)
(spec_dir / "fulfillment-report.md").write_text("generated\n", encoding="utf-8")
```

After the existing generated.txt assertion, add:

```python
assert (
    subprocess.run(
        ["git", "show", f"{salvage_commit}:specs/spec-001-demo/fulfillment-report.md"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    == "generated\n"
)
```

- [ ] **Step 3: Run regression tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage2-env uv run --extra dev pytest tests/unit/test_ralph_commit_push.py tests/unit/test_ralph_outer.py -k "dirty_verify_artifacts or salvages_dirty_worktree or delegates_dirty_verify" -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_ralph_commit_push.py tests/unit/test_ralph_outer.py
git commit -m "test: pin verify artifact commit salvage behavior"
```

## Task 4: Verify Stage 2

- [ ] **Step 1: Run focused tests**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage2-env uv run --extra dev pytest tests/unit/test_ralph_outer.py tests/unit/test_ralph_commit_push.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader harness regression suite**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage2-env uv run --extra dev pytest tests/unit/test_harness_recovery.py tests/unit/test_cli_harness_resume.py tests/unit/test_ralph_outer.py tests/unit/test_ralph_commit_push.py tests/unit/test_run_skill.py tests/unit/test_land.py -q
```

Expected: PASS.

## Self-Review

- Spec coverage: Stage 2 prompt/state labeling is implemented; normal commit and salvage behavior is pinned by tests.
- Placeholder scan: no TBD/TODO/handwave steps remain.
- Scope: This does not implement Stage 3 canonical inventory or Stage 4 scoped verify.
