# EGR-151 Phase A Git Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, real-Git-tested service that plans and creates
an Echelon-owned sibling spec branch from the configured default-branch commit
and returns the prepared run-local spec context required by artifact-only
`speckit.specify`.

**Architecture:** Add `echelon.phase_a_git` as a pure Python boundary over the
existing `echelon.git_helpers` primitives. Planning is read-only: it resolves the
local default branch, allocates the next number across local/remote branches plus
published and run-local spec directories, derives a bounded deterministic slug,
and returns immutable bootstrap metadata. Creation requires a clean worktree
already checked out at the resolved default branch, creates the feature branch
at the recorded default commit, and verifies branch and ancestry before
returning; it does not update `runs/.current` or activate the spec-kit Git
cutover.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, subprocess-backed Git helpers,
pytest, temporary real Git repositories.

## Global Constraints

- Echelon owns branch topology; spec-kit will eventually receive only an explicit
  `SPECIFY_FEATURE_DIRECTORY` and produce artifacts.
- Every new spec branch is a sibling based on the configured default branch,
  never the current feature branch.
- Planning performs no Git or filesystem mutation.
- Branch creation refuses staged, tracked, or untracked dirty changes.
- Branch creation refuses a non-default current branch; checkpoint/switch logic
  must move to the default branch first.
- Number allocation considers `specs/<id>`, `runs/*/specs/<id>`, local branches,
  and remote-tracking branches.
- This slice must not disable spec-kit Git, update `runs/.current`, construct an
  LLM provider, or modify workflow prompts.
- Production behavior is implemented test-first.

---

### Task 1: Read-Only Spec Bootstrap Planning

**Files:**
- Create: `src/echelon/phase_a_git.py`
- Create: `tests/unit/test_phase_a_git.py`

**Interfaces:**
- Consumes: `echelon.git_helpers.run_git()` and a project root plus run directory.
- Produces: `PhaseAGitError`, immutable `PhaseASpecBootstrap`,
  `slugify_spec_description(description: str) -> str`,
  `resolve_phase_a_default_branch(project_root: Path, configured: str = "") -> tuple[str, str]`,
  and `plan_phase_a_spec(project_root: Path, run_dir: Path, description: str, configured_default_branch: str = "") -> PhaseASpecBootstrap`.

- [x] **Step 1: Write failing slug and default-branch tests**

  Add tests asserting:

  ```python
  assert slugify_spec_description("I want to add user authentication") == "add-user-authentication"
  assert slugify_spec_description("Create an OAuth2 API dashboard now") == "create-oauth2-api-dashboard"
  ```

  Initialize real repositories with `main` and `master`; assert explicit
  configuration is authoritative, implicit resolution prefers `main`, and a
  missing explicit default raises `PhaseAGitError`.

- [x] **Step 2: Run tests and verify RED**

  Run: `pytest tests/unit/test_phase_a_git.py -q`

  Expected: collection fails because `echelon.phase_a_git` does not exist.

- [x] **Step 3: Implement slug and default-branch resolution**

  Tokenize ASCII letters/digits, remove only conversational filler
  (`i`, `we`, `want`, `need`, `to`, `a`, `an`, `the`, `please`, `now`), keep the
  first four meaningful tokens, and prefix a single token with `spec-`. Resolve
  explicit configuration only when `refs/heads/<name>` exists; otherwise prefer
  local `main`, then `master`, then the branch named by `refs/remotes/origin/HEAD`.

- [x] **Step 4: Verify GREEN**

  Run: `pytest tests/unit/test_phase_a_git.py -q`

  Expected: slug and default-branch tests pass.

- [x] **Step 5: Add failing collision-safe planning tests**

  Create published `specs/003-old`, run-local `runs/old/specs/007-draft`, local
  branch `005-local`, and remote-tracking ref `origin/009-remote`. Assert the next
  bootstrap is `010-<slug>`, records the exact default commit, uses
  `runs/<run>/specs/010-<slug>` as `spec_dir`, uses
  `specs/010-<slug>` as `published_spec_dir`, and exposes these state updates:

  ```python
  {
      "spec_id": bootstrap.spec_id,
      "spec_number": bootstrap.spec_number,
      "spec_dir": bootstrap.spec_dir,
      "published_spec_dir": bootstrap.published_spec_dir,
      "feature_branch": bootstrap.feature_branch,
      "phase_a_default_branch": bootstrap.default_branch,
      "phase_a_base_commit": bootstrap.default_commit,
      "specify_feature_directory": bootstrap.spec_dir,
  }
  ```

- [x] **Step 6: Implement planning and verify GREEN**

  Run: `pytest tests/unit/test_phase_a_git.py -q`

  Expected: all read-only planning tests pass and `git status --short` remains
  unchanged across `plan_phase_a_spec()`.

### Task 2: Clean Sibling Branch Creation

**Files:**
- Modify: `src/echelon/phase_a_git.py`
- Modify: `tests/unit/test_phase_a_git.py`

**Interfaces:**
- Consumes: `PhaseASpecBootstrap` from Task 1.
- Produces: `create_phase_a_spec_branch(project_root: Path, bootstrap: PhaseASpecBootstrap) -> PhaseASpecBootstrap`.

- [x] **Step 1: Write failing real-Git creation tests**

  Assert successful creation checks out `bootstrap.feature_branch`, leaves
  `HEAD == bootstrap.default_commit`, and makes the default commit an ancestor.
  Add refusal tests for tracked dirt, untracked dirt, current branch not equal to
  `bootstrap.default_branch`, a moved default-branch HEAD, and an already-existing
  target branch. Each refusal must leave branch and HEAD unchanged.

- [x] **Step 2: Run tests and verify RED**

  Run: `pytest tests/unit/test_phase_a_git.py -q`

  Expected: imports or calls fail because `create_phase_a_spec_branch` is absent.

- [x] **Step 3: Implement minimal verified branch creation**

  Validate the current branch, clean worktree, default ref commit, and target ref
  absence before running:

  ```text
  git switch -c <feature_branch> <default_commit>
  ```

  Then verify the observed branch and HEAD exactly match the bootstrap metadata;
  raise `PhaseAGitError` with the failed invariant otherwise.

- [x] **Step 4: Verify GREEN**

  Run: `pytest tests/unit/test_phase_a_git.py -q`

  Expected: all planning and branch-creation tests pass against real temporary
  repositories.

### Task 3: Slice Verification And Commit

**Files:**
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: this plan with observed evidence.

**Interfaces:**
- Consumes: Tasks 1-2 verification evidence.
- Produces: committed EGR-151 bootstrap foundation while retaining
  `in-progress` status and an inactive runtime cutover.

- [x] **Step 1: Run focused and adjacent verification**

  Run:

  ```bash
  pytest tests/unit/test_phase_a_git.py \
    tests/unit/test_speckit_git.py \
    tests/unit/test_cli_spec_switch.py \
    tests/unit/test_cli_resume_spec_context.py \
    tests/integration/test_re_git_flow.py -q
  git diff --check
  ```

  Expected: all selected tests pass and no whitespace errors are reported.

- [x] **Step 2: Record exact evidence without marking EGR-151 fixed**

  Add the passing count and the bootstrap module/test paths to the EGR finding
  and register review log. State explicitly that CLI activation, checkpoints,
  switching, delivery isolation, and finalization remain outstanding.

- [x] **Step 3: Commit only the bootstrap slice**

  Stage the new plan, `src/echelon/phase_a_git.py`,
  `tests/unit/test_phase_a_git.py`, and the two EGR evidence updates. Commit with:

  ```bash
  git commit -m "feat: add Echelon-owned Phase A Git bootstrap"
  ```
