# EGR-151 Exclusive Git Cutover Implementation Plan

> Execute test-first on `codex/egr-151-spec-lifecycle-gitops`. Preserve unrelated working-tree changes and stage only this slice.

**Goal:** Make Echelon the sole Phase A Git authority and start every fresh spec on a sibling branch from the configured default branch.

**Architecture:** Workspace initialization disables spec-kit Git only after workspace Git exists. A focused fresh-spec transaction creates run identity and branch state before changing the active pointer. The squad controller merges that prepared identity into its initial state. Every Phase A provider invocation snapshots branch and HEAD and fails if the external agent mutates either.

**Tech stack:** Python, subprocess Git helpers, pytest; no LLM or network calls in tests.

---

### Task 1: Lock the ownership contract with failing tests

**Files:**
- Modify: `tests/unit/test_workspace_init_deploy_runtime.py`
- Modify: `tests/unit/test_cli_spec_switch.py`
- Modify: `tests/unit/test_squad_provider.py`
- Create: `tests/unit/test_phase_a_start.py`

1. Test that `workspace init` bootstraps Git before disabling spec-kit Git and fails closed if disablement fails.
2. Test that managed Phase A entrypoints reject enabled or malformed spec-kit Git state.
3. Test fresh-spec starts with no prior run and with a checkpointed prior run; assert sibling ancestry, branch selection, run state, and active pointer.
4. Test dirty outgoing changes are refused by default and can be stashed or explicitly discarded.
5. Test provider dispatch rejects branch or HEAD mutation without invoking an LLM.
6. Run the focused tests and confirm the new assertions fail for the intended missing behavior.

### Task 2: Implement the fresh-spec transaction

**Files:**
- Create: `src/echelon/phase_a_start.py`
- Modify: `src/echelon/phase_a_git.py`
- Modify: `src/echelon/spec_switch.py`
- Modify: `src/echelon/spec_lifecycle.py`

1. Expose the existing checkpoint and dirty-worktree resolution primitives for reuse.
2. Add branch-ref creation from the recorded default commit without checking out the default branch.
3. Under the lifecycle lock, validate ownership, recover prior intent, validate the outgoing checkpoint, resolve dirty changes, create the target run state and sibling branch, switch, then atomically replace `runs/.current`.
4. Roll back target state/branch when failure occurs before activation; leave recoverable intent when Git moved but pointer commit did not complete.

### Task 3: Wire CLI and state initialization

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`

1. Add `--stash` and `--discard --confirm` to fresh `echelon spec run` starts.
2. Replace fresh `_setup_run_dir` selection with the new Phase A transaction; keep existing-run resume behavior unchanged.
3. Load the configured `harness.target_default_branch` before fresh selection.
4. Preserve prepared run/spec/Git identity when the controller initializes state.
5. Require exclusive ownership for spec run/continue/resume/manual phase execution.
6. In `workspace init`, bootstrap workspace Git, then disable and verify spec-kit Git.

### Task 4: Guard every Phase A provider boundary

**Files:**
- Modify: `src/harness/squad_provider.py`
- Modify: `tests/unit/test_squad_provider.py`

1. Snapshot current branch and HEAD immediately before each provider call.
2. Verify both after the initial call and any repair call.
3. Raise an actionable ownership error on mutation so Python checkpointing remains the only commit path.

### Task 5: Verify and document the slice

**Files:**
- Modify: `docs/EGR-151-exclusive-git-ownership-and-spec-lifecycle.md`
- Modify: `docs/superpowers/specs/2026-07-17-spec-switch-lifecycle-design.md`

1. Run focused lifecycle, CLI, provider, checkpoint, and workspace tests.
2. Run the broader unit suite if focused tests pass.
3. Inspect `git diff`, `git diff --cached`, and user-owned unstaged paths.
4. Stage only EGR-151 hunks, commit the slice, and update EGR #164 with evidence.

## Plan review

- The sequence removes the branchless interval: workspace Git exists before spec-kit ownership is disabled, while fresh-spec branch creation is enabled in the same slice.
- The active pointer is changed only after a target branch and discoverable target state exist.
- Spec status is deliberately absent from start/switch eligibility; the outgoing checkpoint and dirty-worktree policy are the safety gates.
- Provider tests use deterministic fake backends and local Git repositories, so no LLM is required.
- CLI changes must be partially staged because `src/echelon/cli.py` contains unrelated user changes.
