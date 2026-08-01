# Dirty Worktree Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Echelon autonomously decide whether build-produced dirty target files should be committed, ignored, left alone, or block landing, while recording visible telemetry and status evidence.

**Architecture:** Add a focused `harness.dirty_adjudicator` module that snapshots Git dirt, applies deterministic safety rails, optionally asks an LLM provider for classifications, applies safe decisions in the isolated target worktree, and returns structured evidence. Ralph invokes it after verify passes and before commit/push, persists the evidence in state, and status rendering shows the compact counts.

**Tech Stack:** Python 3.11+, Git CLI, existing `StateStore`, existing `scan_git_staged`, optional `AICodingCliProvider`.

## Global Constraints

- Never mutate the user's source checkout; adjudication runs only in the isolated build worktree.
- Never auto-ignore source-like paths, config, lockfiles, specs, docs, migrations, tests, or already tracked files.
- Never commit staged content that fails the existing secret scan.
- Low-confidence or invalid LLM output falls back to conservative deterministic behavior.
- Every applied decision is persisted in run state and visible through status/banner output.

---

### Task 1: Dirty Adjudicator Core

**Files:**
- Create: `src/harness/dirty_adjudicator.py`
- Test: `tests/unit/test_dirty_adjudicator.py`

**Interfaces:**
- Produces: `adjudicate_dirty_worktree(worktree: Path, *, llm_provider: object | None = None) -> DirtyAdjudicationResult`
- Produces: `DirtyAdjudicationResult.to_state_dict() -> dict[str, object]`

- [x] Write tests for clean worktrees, tracked evidence files, untracked cache files, protected source paths, and invalid LLM fallback.
- [x] Implement Git status parsing using `git status --porcelain=v1 -z --untracked-files=all`.
- [x] Implement safety rails and deterministic classification.
- [x] Implement optional LLM response parsing with strict JSON schema and confidence thresholds.
- [x] Implement `.gitignore` updates for high-confidence ignored untracked output.
- [x] Run `uv run pytest tests/unit/test_dirty_adjudicator.py -q`.

### Task 2: Ralph Integration

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: `adjudicate_dirty_worktree(...)`
- Persists: `state["dirty_worktree_adjudication"]`

- [x] Add a pre-commit adjudication step inside `_commit_and_push`.
- [x] Persist adjudication evidence before commit.
- [x] If adjudication returns `status == "blocked"`, raise `CommitPushError` with a useful summary.
- [x] Preserve existing secret scan behavior during commit.
- [x] Add tests showing dirty evidence is persisted and blocks publish when protected dirt remains.
- [x] Run focused Ralph tests.

### Task 3: Telemetry And Banner Visibility

**Files:**
- Modify: `src/harness/skills/status_skill.py`
- Test: `tests/unit/test_run_skill.py` or `tests/unit/test_cli_status.py`

**Interfaces:**
- Consumes: `dirty_worktree_adjudication.summary`
- Produces: status/banner line such as `dirty: 2 committed, 1 ignored, 0 left, 0 blocked`

- [x] Add compact counts to strategy status payloads.
- [x] Render compact counts in the loop status banner.
- [x] Add tests for status payload and rendered text.
- [x] Run focused status tests.

### Task 4: Regression

**Files:**
- No new files.

- [ ] Run `uv run pytest tests/unit/test_dirty_adjudicator.py tests/unit/test_land_gitops.py tests/unit/test_ralph_outer.py::TestOuterLoopConvergence tests/unit/test_cli_status.py -q`.
- [ ] Run `git diff --check`.
- [ ] Commit the implementation.
