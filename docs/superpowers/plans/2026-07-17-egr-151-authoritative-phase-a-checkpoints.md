# EGR-151 Authoritative Phase A Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every required Phase A checkpoint durable and branch-valid while
committing only the active spec's owned artifacts and blocking orchestration when
checkpoint creation fails.

**Architecture:** Keep the checkpoint ledger as runtime metadata and make the
active `spec_dir` the only Git-owned checkpoint path. A shared helper detects,
stages, and commits changes under that path using Git pathspecs that explicitly
exclude `.echelon/checkpoints.json`; unrelated index and worktree changes remain
untouched. Automatic checkpoints always record the resulting or existing `HEAD`,
and the squad controller converts any required checkpoint failure into a durable
blocked state before another phase can run.

**Tech Stack:** Python 3.11+, pathlib, existing `echelon.git_helpers`, real Git
repositories, pytest.

## Global Constraints

- The runtime spec-kit Git cutover remains inactive in this slice.
- Automatic and manual Phase A checkpoint commits may include only files under
  the resolved active `spec_dir`, excluding its checkpoint ledger.
- `state.json`, journals, `runs/.current`, source files, and unrelated staged,
  tracked, or untracked files are never added by a spec checkpoint.
- A successful phase with no owned file changes still records a checkpoint at
  the current valid `HEAD`.
- Checkpoint ledgers remain runtime metadata and must not make a freshly created
  run dirty.
- A `spec_dir` outside `project_root` fails before Git or ledger mutation.
- Once an active spec directory exists, automatic checkpoint failure is a
  blocking controller error, not a warning.
- Tests use temporary real Git repositories and require no LLM, Docker, or
  network access.
- Production behavior is implemented test-first.

---

### Task 1: Path-Scoped Durable Checkpoint Commits

**Files:**
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Produces: `PhaseCheckpointError` and a non-optional
  `create_phase_checkpoint(...) -> PhaseCheckpoint`.
- Consumes: `project_root`, the active `spec_dir`, phase metadata, and existing
  `run_git()` primitives.
- Internal boundary: `_commit_spec_changes(project_root: Path, spec_dir: Path, message: str) -> str | None`
  returns the new commit SHA or `None` when the owned path has no Git-visible
  changes.

- [x] **Step 1: Write failing real-Git ownership tests**

  Extend the checkpoint fixture to initialize `runs/.gitignore` with:

  ```text
  **/.echelon/checkpoints.json
  */state.json
  .current*
  ```

  Add a test that creates a modified active spec artifact plus three unrelated
  changes: staged `src/staged.txt`, unstaged `README.md`, and untracked
  `scratch.txt`. After `create_phase_checkpoint()`, assert:

  ```python
  assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
      "runs/spec-run/specs/001-demo/tasks.md"
  ]
  assert _git(repo, "diff", "--cached", "--name-only") == "src/staged.txt"
  assert "README.md" in _git(repo, "status", "--short")
  assert "scratch.txt" in _git(repo, "status", "--short")
  assert checkpoint.commit == _git(repo, "rev-parse", "HEAD")
  ```

  Also assert that `PhaseCheckpointError` is raised for a `spec_dir` outside the
  repository and that branch/HEAD/index/ledger state remains unchanged.

- [x] **Step 2: Run the ownership tests and verify RED**

  Run:

  ```bash
  pytest tests/unit/test_phase_checkpoints.py -q
  ```

  Expected: the unrelated staged file appears in the checkpoint commit because
  the current implementation uses `git add -A`, and `PhaseCheckpointError` is
  not defined.

- [x] **Step 3: Implement minimal path-scoped commit helpers**

  Add `PhaseCheckpointError` and helpers that:

  1. resolve `spec_dir` relative to `project_root` or raise;
  2. build an include pathspec for `spec_dir` and an exclusion pathspec for
     `<spec_dir>/.echelon/checkpoints.json`;
  3. run `git add -f -A -- <include> <exclude>` so the explicitly owned spec
     remains branch-durable even when a workspace broadly ignores `/runs/`;
  4. inspect the cached diff only through those pathspecs; and
  5. run `git commit --only -m <message> -- <include> <exclude>` so unrelated
     staged changes remain in the index.

  Wrap `GitHelperError` as `PhaseCheckpointError`. Do not clear, reset, stash,
  or otherwise rewrite unrelated state.

- [x] **Step 4: Make automatic checkpoints non-optional**

  Replace the early `return None` behavior with:

  ```python
  commit = _commit_spec_changes(project_root, spec_dir, message)
  if commit is None:
      commit = run_git(project_root, "rev-parse", "HEAD^{commit}").stdout.strip()
  ```

  Always create and record the `PhaseCheckpoint`, including when `commit` is the
  unchanged current `HEAD`.

- [x] **Step 5: Add the no-change RED/GREEN test**

  Add a test with a clean active spec directory. Assert a non-optional
  checkpoint is returned, `checkpoint.commit == HEAD`, the commit count does not
  increase, and the ledger contains the checkpoint.

  Run:

  ```bash
  pytest tests/unit/test_phase_checkpoints.py -q
  ```

  Expected after implementation: all checkpoint unit tests pass.

- [x] **Step 6: Scope manual checkpoint commits through the same helper**

  Add a failing test for `commit_manual_checkpoint()` with an owned spec change
  and an unrelated staged change. Assert only the spec artifact is committed and
  the unrelated staged file remains staged. Replace its `git add -A` plus raw
  commit with `_commit_spec_changes()`; if the helper returns `None`, raise:

  ```text
  no changes in the active spec directory to commit
  ```

  Run the checkpoint unit file again and verify GREEN.

### Task 2: Keep Checkpoint Ledgers Out Of Git Status

**Files:**
- Modify: `src/echelon/cli.py:2907-2921`
- Create: `tests/unit/test_cli_run_dir_gitignore.py`

**Interfaces:**
- Consumes: `_setup_run_dir(project_root: Path, run_id: str)`.
- Produces: an idempotently maintained `runs/.gitignore` containing
  `**/.echelon/checkpoints.json` while preserving existing user lines.

- [x] **Step 1: Write the failing run-ignore test**

  Seed `runs/.gitignore` with `custom-local-entry\n`, call `_setup_run_dir()`
  twice with different run IDs, and assert:

  ```python
  lines = (project_root / "runs/.gitignore").read_text().splitlines()
  assert "custom-local-entry" in lines
  assert lines.count("**/.echelon/checkpoints.json") == 1
  assert lines.count("*/state.json") == 1
  assert lines.count("*/*.tmp") == 1
  assert lines.count(".current*") == 1
  ```

- [x] **Step 2: Run the test and verify RED**

  Run: `pytest tests/unit/test_cli_run_dir_gitignore.py -q`

  Expected: required defaults are absent because `_setup_run_dir()` only writes
  them when `.gitignore` does not already exist.

- [x] **Step 3: Implement idempotent line preservation**

  Add a private tuple of required patterns and append only missing entries,
  preserving existing order/content and a final newline. Do not overwrite or
  sort user entries.

- [x] **Step 4: Verify run metadata remains clean**

  Add a real-Git test that creates a run through `_setup_run_dir()`, records a
  no-change checkpoint under `runs/<run>/specs/<id>`, and asserts the ledger is
  ignored with:

  ```python
  assert _git(repo, "check-ignore", "runs/<run>/specs/<id>/.echelon/checkpoints.json")
  assert _git(repo, "status", "--short") == ""
  ```

  Run:

  ```bash
  pytest tests/unit/test_cli_run_dir_gitignore.py \
    tests/unit/test_phase_checkpoints.py -q
  ```

  Expected: all tests pass.

### Task 3: Required Checkpoint Failure Blocks Phase A

**Files:**
- Modify: `src/harness/squad.py:670-735,850-920,1237-1255`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Changes: `SquadController._checkpoint_successful_phase(phase: str, next_phase: str) -> bool`.
- Produces: blocked state with `blocked_reason` prefixed
  `phase_checkpoint_failed:` when an active spec checkpoint cannot be created.

- [x] **Step 1: Write the failing controller test**

  Initialize controller state with an existing active `spec_dir`, monkeypatch
  `harness.squad.create_phase_checkpoint` to raise
  `PhaseCheckpointError("simulated checkpoint failure")`, and assert:

  ```python
  assert ctrl._checkpoint_successful_phase("phase3-plan", "phase3-consensus") is False
  state = store.load()
  assert state["status"] == "blocked"
  assert state["phase"] == "terminal-blocked"
  assert state["blocked_reason"] == (
      "phase_checkpoint_failed: phase3-plan: simulated checkpoint failure"
  )
  ```

  Add a success test proving no active spec directory remains a non-blocking
  no-op and an existing spec returns `True` when checkpoint creation succeeds.

- [x] **Step 2: Run the tests and verify RED**

  Run:

  ```bash
  pytest tests/integration/test_squad_controller.py \
    -k "checkpoint_successful_phase" -q
  ```

  Expected: the method returns `None` and logs a warning instead of blocking.

- [x] **Step 3: Implement fail-closed controller behavior**

  Return `True` when no spec exists or checkpoint creation succeeds. On any
  exception after an active spec has resolved, persist:

  ```python
  state["status"] = "blocked"
  state["phase"] = PHASE_TERMINAL_BLOCKED
  state["blocked_reason"] = f"phase_checkpoint_failed: {phase}: {exc}"
  self._state_store.save(state)
  return False
  ```

  At normal, banzai-escalation, manual-phase, and conditional-skip call sites,
  stop/return immediately when the method returns `False`; do not refresh
  context or print a successful phase transition afterward.

- [x] **Step 4: Verify controller and checkpoint regressions**

  Run:

  ```bash
  pytest tests/unit/test_phase_checkpoints.py \
    tests/unit/test_cli_run_dir_gitignore.py \
    tests/integration/test_squad_controller.py -q
  ```

  Expected: all selected tests pass.

### Task 4: EGR Evidence And Slice Commit

**Files:**
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: this plan with observed evidence.

**Interfaces:**
- Consumes: Tasks 1-3 verification evidence.
- Produces: a committed authoritative-checkpoint foundation while EGR-151 stays
  `in-progress` and the ownership cutover stays inactive.

- [x] **Step 1: Run focused adjacent verification**

  Run:

  ```bash
  pytest tests/unit/test_phase_checkpoints.py \
    tests/unit/test_cli_run_dir_gitignore.py \
    tests/unit/test_checkpoint_cli.py \
    tests/unit/test_rewind.py \
    tests/unit/test_cli_rewind.py \
    tests/integration/test_squad_controller.py \
    tests/unit/test_phase_a_git.py \
    tests/unit/test_speckit_git.py -q
  git diff --check
  ```

  If `tests/unit/test_checkpoint_cli.py` is absent, omit it and record that exact
  deviation; checkpoint CLI coverage currently lives in
  `tests/unit/test_cli_delivery.py` and direct checkpoint unit tests.

- [x] **Step 2: Record partial EGR evidence**

  Update the finding, register, and GitHub issue #164 with exact passing counts.
  State that lifecycle resolution/locking, `echelon spec switch`, stash/discard,
  runtime spec-kit disablement, delivery isolation, and finalization remain.
  Keep EGR-151 `in-progress`; do not add the final changelog entry yet.

- [x] **Step 3: Commit only this checkpoint slice**

  Stage the plan, checkpoint implementation/tests, run-ignore implementation/test,
  squad controller/tests, and EGR evidence files. Commit with:

  ```bash
  git commit -m "feat: make Phase A checkpoints authoritative"
  ```
