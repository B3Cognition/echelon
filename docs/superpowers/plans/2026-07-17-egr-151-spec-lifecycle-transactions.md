# EGR-151 Spec Lifecycle Transactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic run resolution and crash-recoverable active-spec
transactions that the future `echelon spec switch` command can use without
guessing by modification time or corrupting `runs/.current`.

**Architecture:** Add a standalone `echelon.spec_lifecycle` module so this slice
does not overlap ongoing CLI work. It discovers well-formed spec runs from
`runs/` plus legacy `squad/`, resolves exact identities before unique numeric
prefixes, serializes lifecycle mutations with an atomic directory lock under
`.echelon/runtime/`, and journals each pointer transition as an atomic switch
intent. Recovery compares the durable intent, current branch supplied by the
caller, and active pointer to either abort a pre-checkout operation, finish a
post-checkout pointer update, clear a completed intent, or fail closed.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, JSON, atomic filesystem
replacement, PID/hostname lock ownership, pytest.

## Global Constraints

- Preserve all pre-existing dirty files; this slice must not modify
  `src/echelon/cli.py`, product-input files, or their tests.
- Runtime spec-kit Git disablement remains inactive.
- Resolution scans only `runs/<name>/state.json` and legacy
  `squad/<name>/state.json`; modification time is never a selector.
- A switchable run requires non-empty `run_id`, `spec_id`, `feature_branch`, and
  `spec_dir` fields plus a readable JSON object state.
- Resolution order is exact run-directory name, exact `run_id`, exact `spec_id`
  or feature branch, then a unique numeric spec prefix.
- Ambiguous identities fail and list deterministic run-directory matches.
- `runs/.current` contains a run-directory name, never a branch or spec ID.
- Pointer replacement uses a sibling temporary file, `fsync`, and atomic
  `Path.replace()`; failure preserves the prior pointer.
- Lock and intent metadata live under `.echelon/runtime/`, which is runtime-only
  workspace state.
- The transaction layer performs no Git checkout, stash, reset, cleanup, or LLM
  invocation. Callers supply the observed current branch.
- Production behavior is implemented test-first.

---

### Task 1: Exact And Ambiguity-Safe Run Resolution

**Files:**
- Create: `src/echelon/spec_lifecycle.py`
- Create: `tests/unit/test_spec_lifecycle.py`

**Interfaces:**
- Produces: `SpecLifecycleError`, `SpecRunNotFound`, `SpecRunAmbiguous`, frozen
  `SpecRun`, `discover_spec_runs(project_root: Path) -> tuple[SpecRun, ...]`,
  `resolve_spec_run(project_root: Path, identity: str) -> SpecRun`, and
  `resolve_active_spec_run(project_root: Path) -> SpecRun`.
- `SpecRun` fields: `run_dir`, `run_dir_name`, `run_id`, `spec_id`,
  `feature_branch`, `spec_dir`, and optional `published_spec_dir`.

- [x] **Step 1: Write failing discovery and exact-resolution tests**

  Create run fixtures with readable state under both `runs/` and `squad/`.
  Assert discovery is sorted by `(run_dir_name, absolute path)` and exact
  resolution works independently for:

  ```python
  assert resolve_spec_run(root, "spec-run-a").run_dir_name == "spec-run-a"
  assert resolve_spec_run(root, "runtime-id-a").run_id == "runtime-id-a"
  assert resolve_spec_run(root, "001-spec-a").spec_id == "001-spec-a"
  assert resolve_spec_run(root, "feature/001-spec-a").feature_branch == "feature/001-spec-a"
  ```

  Add malformed JSON, non-object JSON, and missing-field run directories and
  assert discovery skips them without choosing a fallback by mtime.

- [x] **Step 2: Run the resolver tests and verify RED**

  Run: `pytest tests/unit/test_spec_lifecycle.py -q`

  Expected: collection fails because `echelon.spec_lifecycle` does not exist.

- [x] **Step 3: Implement immutable discovery records**

  Resolve relative `spec_dir` and `published_spec_dir` against `project_root`.
  Require `spec_dir` to remain inside the project root; skip malformed/outside
  records. Deduplicate the same resolved run directory and return a tuple sorted
  without timestamps.

- [x] **Step 4: Implement priority-ordered exact resolution**

  For each priority tier, return one match, raise `SpecRunAmbiguous` for multiple
  matches in that tier, or continue. `SpecRunAmbiguous.matches` is the sorted
  tuple of matching `SpecRun` values. Empty identities raise `SpecRunNotFound`.

- [x] **Step 5: Add failing numeric-prefix and active-pointer tests**

  Assert numeric `001` resolves `001-spec-a`, while two `001-*` states raise an
  ambiguity listing both run names. Write `runs/.current` with a run-directory
  name and assert `resolve_active_spec_run()` resolves it. Missing, blank,
  unknown, and spec-ID-valued pointers must fail without guessing.

- [x] **Step 6: Implement prefix and active-pointer resolution; verify GREEN**

  Numeric prefix matching uses `^(\d+)(?:-|$)` against `spec_id` and
  `feature_branch` basename only after all exact tiers fail. Active resolution
  reads only `runs/.current` and requires its content to exactly equal the
  resolved run's `run_dir_name`.

  Run: `pytest tests/unit/test_spec_lifecycle.py -q`

  Expected: all resolver tests pass.

### Task 2: Single-Writer Lifecycle Lock

**Files:**
- Modify: `src/echelon/spec_lifecycle.py`
- Modify: `tests/unit/test_spec_lifecycle.py`

**Interfaces:**
- Produces: `SpecLifecycleLocked`, `SpecLifecycleRecoveryRequired`, and context
  manager `SpecLifecycleLock.acquire(project_root: Path, operation_id: str) -> SpecLifecycleLock`.
- Lock path: `.echelon/runtime/spec-lifecycle.lock/owner.json`.

- [x] **Step 1: Write failing lock ownership tests**

  Assert the first acquisition writes `operation_id`, PID, hostname, and an ISO
  timestamp; a second live acquisition raises `SpecLifecycleLocked` naming the
  first operation; context exit removes the lock directory; and releasing a lock
  whose owner metadata changed raises without deleting another owner's lock.

- [x] **Step 2: Run focused lock tests and verify RED**

  Run: `pytest tests/unit/test_spec_lifecycle.py -k "lifecycle_lock" -q`

  Expected: imports/calls fail because the lock types are absent.

- [x] **Step 3: Implement atomic directory acquisition and verified release**

  Validate operation IDs with `^[A-Za-z0-9._-]+$`, acquire using `mkdir()`
  without `exist_ok`, and write owner JSON atomically. If owner writing fails,
  remove the newly created lock directory. Release rereads owner metadata and
  removes the directory only when the operation IDs match.

- [x] **Step 4: Add dead-local-owner recovery test**

  Seed owner metadata with the local hostname and a guaranteed-dead positive
  PID. Assert acquisition removes that stale lock and installs the new owner.
  Malformed owner JSON, unsafe IDs, invalid PIDs, and different-host locks raise
  `SpecLifecycleRecoveryRequired` instead of being silently reclaimed.

- [x] **Step 5: Implement fail-closed stale-lock handling; verify GREEN**

  Reclaim only when hostname equals `socket.gethostname()`, PID is a positive
  non-boolean integer, and `os.kill(pid, 0)` raises `ProcessLookupError`.

  Run: `pytest tests/unit/test_spec_lifecycle.py -q`

  Expected: resolver and lock tests pass.

### Task 3: Atomic Pointer And Crash-Recoverable Switch Intent

**Files:**
- Modify: `src/echelon/spec_lifecycle.py`
- Modify: `tests/unit/test_spec_lifecycle.py`

**Interfaces:**
- Produces: frozen `SpecSwitchIntent`, frozen `SpecSwitchRecovery`,
  `begin_spec_switch(...) -> SpecSwitchIntent`,
  `load_spec_switch_intent(project_root: Path) -> SpecSwitchIntent | None`,
  `mark_spec_switch_checked_out(project_root: Path, operation_id: str, observed_branch: str) -> SpecSwitchIntent`,
  `commit_spec_switch_pointer(project_root: Path, operation_id: str, observed_branch: str) -> SpecRun`, and
  `recover_spec_switch(project_root: Path, observed_branch: str) -> SpecSwitchRecovery`.
- Intent path: `.echelon/runtime/spec-switch-intent.json`.
- Pointer path: `runs/.current`.

- [x] **Step 1: Write failing atomic-pointer tests**

  Begin with an existing pointer. Monkeypatch `Path.replace` to raise during
  pointer replacement and assert the old pointer remains byte-for-byte intact
  and temporary files are removed. On success, assert the pointer contains only
  `<target-run-dir-name>\n` and resolves through `resolve_active_spec_run()`.

- [x] **Step 2: Write failing intent lifecycle tests**

  With source active and caller-observed source branch, assert
  `begin_spec_switch()` writes a `prepared` intent containing operation/source/
  target run names and branches. A second begin refuses to overwrite it.
  `mark_spec_switch_checked_out()` accepts only the intent's target branch and
  atomically changes the stage to `checked_out`.

- [x] **Step 3: Run pointer/intent tests and verify RED**

  Run: `pytest tests/unit/test_spec_lifecycle.py -k "pointer or intent" -q`

  Expected: functions/types are absent.

- [x] **Step 4: Implement atomic JSON and pointer writers**

  Use `tempfile.mkstemp()` in the destination directory, flush and `os.fsync()`,
  then `Path.replace()`. Always remove a leftover temporary path on failure.
  Parse intent JSON strictly: missing fields, invalid stages, or non-object JSON
  raise `SpecLifecycleRecoveryRequired`.

- [x] **Step 5: Implement begin, mark, and commit invariants**

  `begin_spec_switch()` requires the active pointer and observed branch to match
  the source run. `mark_spec_switch_checked_out()` requires matching operation
  ID and target branch. `commit_spec_switch_pointer()` requires the target branch,
  atomically writes the target run-directory name, then clears only the matching
  intent. If clearing fails after pointer replacement, leave the intent so
  recovery can finish idempotently.

- [x] **Step 6: Write failing crash-recovery matrix**

  Cover these exact cases:

  | Intent | Pointer | Branch | Result |
  |---|---|---|---|
  | prepared | source | source | clear intent, `aborted_before_checkout` |
  | prepared | source | target | set target pointer, clear intent, `completed_after_checkout` |
  | checked_out | source | target | set target pointer, clear intent, `completed_after_checkout` |
  | checked_out | target | target | clear intent, `cleared_completed_intent` |
  | any | inconsistent | unrelated | raise with no mutation |

- [x] **Step 7: Implement recovery and verify GREEN**

  Recovery resolves source and target by exact run-directory names from the
  intent, reads the pointer without fallback, applies only the table above, and
  returns `SpecSwitchRecovery(action, source, target)`. It does not invoke Git.

  Run: `pytest tests/unit/test_spec_lifecycle.py -q`

  Expected: all resolver, lock, pointer, intent, and recovery tests pass.

### Task 4: EGR Evidence And Slice Commit

**Files:**
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: this plan with observed evidence.

**Interfaces:**
- Consumes: Tasks 1-3 verification evidence.
- Produces: a committed lifecycle-transaction foundation while preserving all
  pre-existing user changes and keeping EGR-151 `in-progress`.

- [x] **Step 1: Run focused adjacent verification**

  Run:

  ```bash
  pytest tests/unit/test_spec_lifecycle.py \
    tests/unit/test_phase_a_git.py \
    tests/unit/test_phase_checkpoints.py \
    tests/unit/test_cli_spec_switch.py \
    tests/unit/test_cli_resume_spec_context.py \
    tests/unit/test_speckit_git.py -q
  git diff --check -- \
    src/echelon/spec_lifecycle.py \
    tests/unit/test_spec_lifecycle.py \
    docs/superpowers/plans/2026-07-17-egr-151-spec-lifecycle-transactions.md \
    docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md \
    docs/findings/echelon-grounded-review-register.md
  ```

- [x] **Step 2: Record partial EGR evidence**

  Update the finding, register, and GitHub issue #164 with exact passing counts.
  State that Git validation/checkout, stash/discard, CLI wiring, the atomic
  spec-kit ownership cutover, delivery isolation, and finalization remain.

- [x] **Step 3: Commit only this transaction slice**

  Confirm the five slice paths are the only staged files, then commit with:

  ```bash
  git commit -m "feat: add transactional spec lifecycle state"
  ```

  Do not stage the pre-existing dirty CLI, product-input, workflow, or test files.

## Observed Evidence

- The resolver test first failed at collection because
  `echelon.spec_lifecycle` did not exist.
- Lock and switch-transaction tests were also observed failing before their
  respective interfaces were implemented.
- The external run-directory symlink regression failed before containment was
  enforced, then passed with the full lifecycle suite.
- Final focused verification on 2026-07-17 passed 73 tests across lifecycle
  state, Phase A Git, checkpoint authority, existing switch/resume routing, and
  spec-kit Git inspection.
- GitHub issue #164 was refreshed from the grounded finding after verification.
