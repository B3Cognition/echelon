# EGR-151 Checkpoint-Gated Spec Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, no-LLM `echelon spec switch <spec-or-run-id>`
command that validates both runs' Phase A checkpoints and safely handles clean,
stashed, restored, or explicitly discarded worktree state.

**Architecture:** Keep Git mutation in a focused `echelon.spec_switch` service
that composes the committed `spec_lifecycle`, `git_helpers`, `speckit_git`, and
Phase A checkpoint primitives. Add a thin `spec_switch_cli` parser/presenter so
`cli.py` needs only help and dispatch hooks. Every switch runs under the
lifecycle lock, recovers an interrupted intent first, mutates Git before the
active pointer, and records managed stash identity by immutable commit SHA in
the owning run state.

**Tech Stack:** Python 3.11+, pathlib, dataclasses, JSON, subprocess-backed Git,
UUID operation IDs, pytest with temporary real Git repositories.

## Global Constraints

- Preserve the pre-existing dirty workflow, CLI, product-input, and test files.
- Stage only EGR-151 hunks from `src/echelon/cli.py`; never stage the user's
  unrelated CLI recovery changes.
- Invoke no LLM, Docker runtime, or network service in implementation tests.
- Refuse switching unless `require_speckit_git_disabled()` confirms exclusive
  Echelon Git ownership.
- Do not automatically disable spec-kit Git in this slice. The workspace-init,
  new-spec bootstrap, and fail-closed global Phase A cutover remain atomic work
  for the next slice.
- Resolve runs only through `resolve_spec_run()` and `resolve_active_spec_run()`;
  never infer from mtimes.
- Leaving a run requires its latest ledger entry for the same `run_id` and
  `spec_id`, an existing commit, and containment by its exact feature branch.
- Existing targets require the same checkpoint validation and an existing local
  branch.
- A dirty non-interactive switch fails unless exactly one of `--stash` or
  `--discard --confirm` is present.
- Managed stash state stores the stash commit SHA, never `stash@{N}`.
- Discard resets tracked/staged work to the validated outgoing checkpoint and
  uses `git clean -fd`, which preserves ignored runtime state.
- Git checkout precedes `runs/.current` replacement. Checkout failure leaves the
  pointer unchanged and the durable intent recoverable.
- Production behavior is implemented test-first.

---

### Task 1: Checkpoint Validation And Clean Switching

**Files:**
- Create: `src/echelon/spec_switch.py`
- Create: `tests/unit/test_spec_switch.py`

**Interfaces:**
- Consumes: `SpecRun`, `SpecLifecycleLock`, switch-intent functions,
  `load_checkpoint_ledger`, `commit_exists`, `ref_contains_commit`, and
  `require_speckit_git_disabled`.
- Produces: `SpecSwitchError`, frozen `ValidatedSpecCheckpoint`, frozen
  `SpecSwitchOutcome`, `validate_spec_checkpoint(project_root, run)`, and
  `switch_spec(project_root, identity, *, dirty_action="refuse",
  confirm_discard=False, restore_stash=False) -> SpecSwitchOutcome`.

- [x] **Step 1: Write failing checkpoint validation tests**

  Create temporary real Git repositories containing `main`, sibling
  `001-spec-a` and `002-spec-b` branches, ignored run state/ledgers, and exact
  `runs/.current` state. Assert validation selects the last checkpoint whose
  `run_id` and `spec_id` both match the run, and rejects:

  ```python
  with pytest.raises(SpecSwitchError, match="no checkpoint"):
      validate_spec_checkpoint(repo, run)
  with pytest.raises(SpecSwitchError, match="does not exist"):
      validate_spec_checkpoint(repo, run_with_unknown_commit)
  with pytest.raises(SpecSwitchError, match="does not contain"):
      validate_spec_checkpoint(repo, run_with_checkpoint_from_other_branch)
  ```

- [x] **Step 2: Run validation tests and verify RED**

  Run: `pytest tests/unit/test_spec_switch.py -k checkpoint -q`

  Expected: collection fails because `echelon.spec_switch` does not exist.

- [x] **Step 3: Implement strict checkpoint validation**

  Load `run.spec_dir/.echelon/checkpoints.json`, wrap malformed ledgers as
  `SpecSwitchError`, scan entries in reverse, and require exact run/spec
  identity. Return:

  ```python
  @dataclass(frozen=True)
  class ValidatedSpecCheckpoint:
      checkpoint_id: str
      phase: str
      commit: str
      run: SpecRun
  ```

  Verify the commit object, local `refs/heads/<feature_branch>`, and ancestor
  containment without checking out the branch.

- [x] **Step 4: Write failing clean-switch and recovery tests**

  Assert A -> B checks out B and atomically changes `.current`; switching B
  again is idempotent; detached HEAD, source-branch mismatch, missing target
  branch, and enabled spec-kit Git all fail without pointer mutation. Simulate
  `git switch` failure and assert the pointer remains A with a prepared intent;
  the next invocation must recover that intent and complete normally.

- [x] **Step 5: Run clean-switch tests and verify RED**

  Run: `pytest tests/unit/test_spec_switch.py -k "clean or idempotent or checkout or ownership" -q`

  Expected: tests fail because `switch_spec()` is absent.

- [x] **Step 6: Implement lifecycle-locked clean switching**

  Generate one UUID operation ID, acquire `SpecLifecycleLock`, require exclusive
  ownership, recover any existing intent using the observed branch, resolve
  exact source/target runs, validate checkpoints and branches, and require the
  observed branch to equal the source feature branch. For a real switch call:

  ```python
  begin_spec_switch(...)
  run_git(root, "switch", target.feature_branch)
  mark_spec_switch_checked_out(...)
  commit_spec_switch_pointer(...)
  ```

  Return an outcome containing source, target, their validated checkpoints, the
  operation action, and empty stash fields.

- [x] **Step 7: Run Task 1 tests and verify GREEN**

  Run: `pytest tests/unit/test_spec_switch.py -q`

  Expected: checkpoint and clean-switch tests pass.

### Task 2: Managed Stash, Restoration, And Confirmed Discard

**Files:**
- Modify: `src/echelon/spec_switch.py`
- Modify: `tests/unit/test_spec_switch.py`

**Interfaces:**
- Produces: `DirtySpecWorktreeError` with porcelain paths; run-state field
  `phase_a_stash = {commit, branch, checkpoint_id, checkpoint_commit,
  created_at}`; stash/restore/discard behavior through `switch_spec()`.

- [x] **Step 1: Write failing dirty-refusal tests**

  Dirty tracked, staged, and untracked paths in the real repository. Assert the
  default action raises `DirtySpecWorktreeError`, reports all Git-visible paths,
  and preserves branch, HEAD, pointer, and both run states.

- [x] **Step 2: Run dirty-refusal test and verify RED**

  Run: `pytest tests/unit/test_spec_switch.py -k dirty_refusal -q`

  Expected: import or assertion failure because dirty classification is absent.

- [x] **Step 3: Implement deterministic porcelain inspection**

  Parse `git status --porcelain=v1 -z --untracked-files=all`; expose sorted
  paths and refuse unknown `dirty_action` values. Ignore ignored files by relying
  on Git's status result rather than filesystem traversal.

- [x] **Step 4: Write failing managed-stash and restoration tests**

  Switch dirty A -> B with `dirty_action="stash"`. Assert the worktree becomes
  clean, A state records `refs/stash`'s commit SHA, and no selector is stored.
  Then switch clean B -> A with `restore_stash=True`; assert A's changes return,
  the exact stash entry is dropped only after successful apply, and the run-state
  record is cleared. Seed an apply conflict and assert the stash entry and state
  record remain for manual recovery. Refuse overwriting an existing managed
  stash record.

- [x] **Step 5: Run stash tests and verify RED**

  Run: `pytest tests/unit/test_spec_switch.py -k stash -q`

  Expected: stash behavior is not implemented.

- [x] **Step 6: Implement immutable stash recording and restoration**

  Use `git stash push --include-untracked --message <run/spec/branch>`, resolve
  `refs/stash^{commit}`, and atomically update the ignored run `state.json`.
  Before restore, locate the durable SHA in `git stash list
  --format=%gd%x00%H`; apply by SHA, drop the resolved selector only after a
  zero exit, then atomically remove `phase_a_stash`. A failed apply raises after
  the branch/pointer switch and preserves both records.

- [x] **Step 7: Write failing confirmed-discard tests**

  Assert `dirty_action="discard"` without confirmation refuses without
  mutation. With confirmation, assert tracked and staged changes reset to the
  source checkpoint, Git-reported untracked files/directories are removed,
  ignored run state survives, and the switch completes. Assert reset/clean
  failure leaves the pointer on the source.

- [x] **Step 8: Run discard tests and verify RED**

  Run: `pytest tests/unit/test_spec_switch.py -k discard -q`

  Expected: discard behavior is absent.

- [x] **Step 9: Implement checkpoint-only discard and verify GREEN**

  Require `confirm_discard`, run `git reset --hard <checkpoint.commit>` followed
  by `git clean -fd`, verify a clean worktree, then enter the normal switch
  transaction. Run:

  `pytest tests/unit/test_spec_switch.py -q`

  Expected: all clean, dirty, stash, restore, discard, and recovery tests pass.

### Task 3: Thin CLI Parsing And Dispatch

**Files:**
- Create: `src/echelon/spec_switch_cli.py`
- Create: `tests/unit/test_spec_switch_cli.py`
- Modify only EGR hunks: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_spec_switch.py`

**Interfaces:**
- Produces: frozen `SpecSwitchOptions`,
  `parse_spec_switch_args(args) -> SpecSwitchOptions`, and
  `run_spec_switch_command(args, *, project_root, stdin, stdout, stderr) -> int`.
- Adds: `echelon spec switch <spec-or-run-id> [--stash | --discard --confirm]
  [--restore-stash]`.

- [x] **Step 1: Write failing option-parser tests**

  Assert one identity is required; stash/discard are mutually exclusive;
  `--confirm` is accepted only with `--discard`; unknown flags fail; and
  `--restore-stash` composes with either clean or dirty handling.

- [x] **Step 2: Run parser tests and verify RED**

  Run: `pytest tests/unit/test_spec_switch_cli.py -q`

  Expected: collection fails because `echelon.spec_switch_cli` is absent.

- [x] **Step 3: Implement parser and non-interactive presentation**

  Map engine errors to concise stderr and exit code 1. Print source/target run,
  target branch, checkpoint ID/SHA, stash action, and next command on success.
  A non-interactive dirty refusal must list paths and show exact `--stash` and
  `--discard --confirm` retry commands.

- [x] **Step 4: Write failing interactive-choice tests**

  With a scripted TTY stream, assert `[s]` retries with stash, `[d]` asks a
  second confirmation before discard, and empty/`c` cancels without mutation.
  These tests may replace `switch_spec` at the presenter boundary; all Git
  behavior remains covered by Task 1-2 real-repository tests.

- [x] **Step 5: Implement interactive choice handling and verify GREEN**

  Default to cancel. Never infer destructive confirmation from choosing `d`;
  require an explicit `y`/`yes` response before passing
  `confirm_discard=True`.

  Run: `pytest tests/unit/test_spec_switch_cli.py -q`

  Expected: parser and presenter tests pass.

- [x] **Step 6: Add CLI help/dispatch tests and observe RED**

  Extend `tests/unit/test_cli_spec_switch.py` to call `_cmd_spec(["switch", ...])`
  with the presenter replaced, assert arguments/project root are forwarded, and
  assert both `USAGE` and spec help document every flag. The existing
  preservation test must remain unchanged.

- [x] **Step 7: Add minimal `cli.py` help and dispatch hunks**

  Add the switch syntax to the global and spec-specific help, plus one
  `elif subcmd == "switch"` branch importing `run_spec_switch_command`. Exit
  only when it returns nonzero. Do not edit or stage the user's
  `_classify_run_recovery` or `_cmd_continue` hunks.

- [x] **Step 8: Run CLI verification**

  Run:

  ```bash
  pytest tests/unit/test_spec_switch_cli.py \
    tests/unit/test_cli_spec_switch.py -q
  ```

  Expected: all switch and command-help tests pass.

### Task 4: EGR Evidence And Isolated Commit

**Files:**
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: this plan with observed evidence.

**Interfaces:**
- Produces: the committed checkpoint-gated existing-run switch while EGR-151
  remains `in-progress` for automatic ownership cutover, new-spec bootstrap,
  delivery isolation, and finalization.

- [x] **Step 1: Run focused real-Git and adjacent verification**

  Run:

  ```bash
  pytest tests/unit/test_spec_switch.py \
    tests/unit/test_spec_switch_cli.py \
    tests/unit/test_spec_lifecycle.py \
    tests/unit/test_phase_a_git.py \
    tests/unit/test_phase_checkpoints.py \
    tests/unit/test_cli_spec_switch.py \
    tests/unit/test_cli_resume_spec_context.py \
    tests/unit/test_speckit_git.py -q
  ```

  Record the exact count and run `git diff --check` on all slice paths.

- [x] **Step 2: Update EGR-151 and issue #164**

  Record clean/stash/restore/discard/recovery coverage and state explicitly that
  automatic spec-kit disablement, fail-closed global Phase A preflight,
  Echelon-owned new-spec bootstrap, delivery isolation, and finalization remain.

- [x] **Step 3: Stage only the isolated slice**

  Stage new modules/tests/docs normally. Build a zero-context patch containing
  only the switch help/dispatch hunks from `src/echelon/cli.py` and apply that
  patch to the index with `git apply --cached`; do not stage the user's existing
  CLI hunks. Verify `git diff --cached -- src/echelon/cli.py` contains only the
  switch additions.

- [x] **Step 4: Commit and post-commit verify**

  Commit with:

  ```bash
  git commit -m "feat: add checkpoint-gated spec switching"
  ```

  Re-run the focused matrix, `git diff --check HEAD^ HEAD`, and confirm the
  pre-existing user files remain unstaged.

## Observed Evidence

- Checkpoint tests first failed at collection because `echelon.spec_switch` did
  not exist; clean-switch tests then failed because `switch_spec` was absent.
- Dirty refusal, stash/restore, and discard tests each failed against the
  preceding minimal implementation before their behavior was added.
- CLI tests first failed at collection because `echelon.spec_switch_cli` did not
  exist, then spec help/dispatch failed until the thin `cli.py` hooks were added.
- A review regression proved failed `git status` inspection previously appeared
  clean; the engine now fails closed before checkout or pointer mutation.
- Final pre-documentation verification on 2026-07-17 compiled both new modules
  and passed 112 focused/adjacent tests without LLM, Docker, or network access.
- GitHub issue #164 was refreshed from the grounded finding after verification.
