# Landing Lifecycle Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make successful landing publish terminal spec state, report that state consistently, and leave Echelon-owned checkouts clean.

**Architecture:** A focused workspace finalization module owns bounded spec commit, existing spec publication reuse, default-branch checkout, and clean-status validation. Both landing completion paths call it before clearing authoring state. The CLI short-circuits Phase A readiness when canonical spec frontmatter is terminal.

**Tech Stack:** Python 3.11+, Git CLI, pytest, existing `echelon.spec_publish`, Rich CLI banners.

**Spec:** `docs/superpowers/specs/2026-09-03-landing-lifecycle-finalization-design.md`

## Global Constraints

- Never delete unknown tracked or untracked user files.
- Stage and commit only the canonical `specs/<spec-id>` subtree.
- Run the existing staged-secret scan before every Echelon-authored commit.
- Reuse `publish_specs()` rather than implementing a second publication path.
- A successful landing requires clean implementation and orchestration checkouts.
- Terminal `landed` status suppresses all build or delivery suggestions.

---

### Task 1: Workspace landing finalizer

**Files:**
- Create: `src/harness/workspace_landing.py`
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_workspace_landing.py`
- Test: `tests/unit/test_land.py`

**Interfaces:**
- Consumes: `publish_specs(project_root, identity=spec_id)`, `write_status(spec_dir, "landed")`, and Git repositories already prepared by `land()`.
- Produces: `finalize_workspace_landing(spec_id: str, workspace_root: Path, target_root: Path) -> WorkspaceLandingResult`, where the result contains `ok`, `reason`, `paths`, and publication provenance.

- [x] **Step 1: Write failing tests for polyrepo finalization**

Create real temporary Git repositories with a canonical spec branch. Assert the
finalizer commits all terminal spec changes, publishes the exact snapshot to
workspace `main`, switches the caller to `main`, and leaves `git status
--porcelain` empty.

- [x] **Step 2: Run the focused tests and confirm the missing module failure**

Run: `pytest -q tests/unit/test_workspace_landing.py`

Expected: collection fails because `harness.workspace_landing` does not exist.

- [x] **Step 3: Implement bounded commit and publication**

Implement `WorkspaceLandingResult` and `finalize_workspace_landing`. Resolve the
spec path with `find_spec_dir`, require it to be inside the workspace, stage only
that relative path, run `scan_git_staged`, commit with
`build_echelon_commit_message`, invoke `publish_specs` only when workspace and
target differ, then switch to the resolved default branch.

- [x] **Step 4: Add failure and idempotence tests**

Cover secret-scan rejection, publication failure, unrelated dirty workspace
paths, a no-op repeated finalization, and monorepo direct commit. Assert unknown
paths remain untouched and are returned in `WorkspaceLandingResult.paths`.

- [x] **Step 5: Integrate both landing completion paths**

Replace direct `write_status` and pointer clearing in `_finish_landing` and
`_finish_branchless_landing` with the finalizer. Render a bounded failure banner
and return false when finalization does not complete. Clear the pointer only
after finalization succeeds.

- [x] **Step 6: Run landing regression tests**

Run: `pytest -q tests/unit/test_workspace_landing.py tests/unit/test_land.py`

Expected: all tests pass.

### Task 2: Terminal lifecycle-aware spec status

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_status.py`
- Test: `tests/unit/test_cli_next_step_escalation.py`

**Interfaces:**
- Consumes: canonical spec paths already selected by `_print_next_steps` and `read_frontmatter`.
- Produces: `_terminal_spec_status(spec_dir: Path | None) -> str | None` and a `LANDED` next-step panel.

- [x] **Step 1: Write a failing landed-status regression test**

Create a completed Phase A run whose canonical published spec has
`status: landed`. Assert output contains `LANDED`, excludes `READY TO BUILD`,
and excludes `echelon delivery run`.

- [x] **Step 2: Run the exact regression and confirm the old readiness output**

Run: `pytest -q tests/unit/test_cli_status.py -k landed`

Expected: failure because the output still contains `READY TO BUILD`.

- [x] **Step 3: Implement the terminal short-circuit**

After canonical spec selection and before quality/readiness calculation, read
frontmatter. For `landed`, render spec id, lifecycle status, and `No action
required; delivery is already landed.`, then return.

- [x] **Step 4: Run CLI status regressions**

Run: `pytest -q tests/unit/test_cli_status.py tests/unit/test_cli_next_step_escalation.py`

Expected: all tests pass and existing blocked/readiness guidance is unchanged.

### Task 3: Checkout cleanliness and demo ignore hygiene

**Files:**
- Modify: `src/harness/workspace_landing.py`
- Modify: `src/harness/land.py`
- Modify: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/.gitignore`
- Test: `tests/unit/test_workspace_landing.py`
- Test: `tests/unit/test_land.py`

**Interfaces:**
- Consumes: `git status --porcelain --untracked-files=all` for both owned checkouts.
- Produces: exact residual-path diagnostics without deleting any path.

- [x] **Step 1: Write failing cleanliness tests**

Assert a successful finalizer refuses unknown untracked workspace residue and a
successful target land refuses post-landing residue. Verify the files still
exist after refusal.

- [x] **Step 2: Implement full-status postconditions**

Parse porcelain status without destructive cleanup. Return exact paths and make
landing render `LAND — CHECKOUT NOT CLEAN` with a retry command.

- [x] **Step 3: Add durable demo ignores**

Add `/test-results/`, `/playwright-report/`, `/blob-report/`, and `/coverage/`
to the demo target `.gitignore`. Commit the ignore change without deleting the
existing report files.

- [x] **Step 4: Run focused and full verification**

Run: `pytest -q tests/unit/test_workspace_landing.py tests/unit/test_land.py tests/unit/test_cli_status.py tests/unit/test_cli_next_step_escalation.py`

Then run the repository's complete unit suite command discovered from CI or
project documentation and confirm zero failures.

- [ ] **Step 5: Verify real repository state**

Run `git status --short --branch` in Echelon main/worktree, the demo workspace,
and the demo target. Confirm the implementation checkout is clean and document
any intentionally pending workspace lifecycle changes that the repaired land
command must consume.
