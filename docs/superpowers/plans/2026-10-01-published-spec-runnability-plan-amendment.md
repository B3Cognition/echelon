# Published Spec Runnability Plan Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Echelon append a missing runnability-contract owner to a published Spec and continue Delivery without redoing checkpoint-proven work or hand-editing generated product files.

**Architecture:** A typed, deterministic planner proposes only new owner tasks. An isolated Spec amendment prepares their commit; an amendment-specific journal promotes its file, index, and branch effects in that order. Fresh Delivery may inherit old task progress only through a promoted amendment record, the old full-plan hash, and target-local checkpoint ancestry.

**Tech Stack:** Python 3, Typer CLI, Git, existing Echelon Spec amendment, publication, task-progress, and Delivery modules; pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-published-spec-runnability-plan-amendment-design.md`

## Global Constraints

- The only trigger is a published plan missing a canonical owner for a stack-required target-qualified `.echelon/runnability.yml`; an explicit valid deferral is not missing ownership.
- Normal new Spec PLAN/readiness and existing Delivery four-role review, fulfillment, browser, visual, and final gates remain unchanged.
- Never hand-edit generated demo source, tests, screenshots, baselines, Spec artifacts, or Delivery state to make this acceptance run pass.
- Never reconcile an unknown dispatch through this amendment. It must recover under its original sealed inputs first.
- Do not revive an old candidate from another target, an old plan hash, or an unaccepted provider result.
- The preserved workspace is read-only until a disposable functional path and its exact carry-forward eligibility pass.
- Keep CLI routing thin; policy belongs to the Spec/Delivery harness, not command parsing.
- Do not run the repository-wide suite after every task. Run the task's focused tests and functional check; run broader verification and review once at the end.

## File map and ownership

- Create `src/harness/runnability_amendment_plan.py`: pure target/owner analysis, canonical task append, and working-progress projection. It neither writes files nor reads run state.
- Create `src/echelon/runnability_amendment.py`: typed preview and isolated preparation, using existing `spec_amendment.py` locks, baseline, worktree, and state conventions.
- Create `src/echelon/runnability_amendment_transaction.py`: one durable amendment journal coordinating file publication with exact Git index and ref effects.
- Create `src/harness/amendment_lineage.py`: validate promoted amendment evidence and return proven completed task IDs for exactly one target/candidate.
- Modify `src/echelon/cli_app.py` and `src/echelon/spec_service.py`: thin `spec amend ... --runnability-owner` preview/prepare and `spec amend promote <id>` routing; leave pre-build amendment behavior intact.
- Modify `src/harness/skills/run_skill.py`: call target-local amendment lineage only when a promoted record applies; retain exact-hash behavior otherwise.
- Add focused tests beside existing amendment, CLI, and checkpoint-recovery tests. One disposable integration test owns the end-to-end transition.

## Review Focus

- A required stack with a valid deferral: preview reports no task and performs no write (Task 1 test).
- Progress-only dirty `tasks.md` plus staged unrelated content: promotion retains both exactly (Task 3 test).
- A user edit between file installation and recovery: recovery does not overwrite it and blocks admission (Task 3 test).
- Two targets with similarly named checkpoints: only each target's own old-hash, ancestor checkpoint carries (Task 4 test).
- A completed-looking checkbox without an accepted checkpoint: Delivery selects/reviews that task or blocks; it never inherits the checkbox (Task 4 test).

---

### Task 1: Pure owner-task proposal and preview

**Files:**
- Create: `src/harness/runnability_amendment_plan.py`
- Test: `tests/unit/test_runnability_amendment_plan.py`

**Interfaces:**
- Consumes: published `tasks.md` text; canonical target IDs; required target IDs after stack resolution and valid deferrals; working `tasks.md` text.
- Produces: `OwnerTaskProposal(target_id: str, task_id: str, contract_path: str, markdown: str)` and `plan_owner_tasks(published_tasks: str, working_tasks: str, targets: tuple[str, ...], required_targets: tuple[str, ...]) -> tuple[OwnerTaskProposal, ...]`; `project_progress(published_tasks: str, working_tasks: str, proposed_tasks: str) -> str`.

- [ ] **Step 1: Write the failing tests.** Use canonical rows like the real published plan, not only a fabricated header:

```python
def test_missing_owner_appends_one_pending_target_qualified_task():
    published = ("## Summary\n\n- Total tasks: 1\n\n## Phase: Release\n"
                 "- [ ] T-001 complexity=standard phase=release req=INFRA depends=none target=apps/web\n"
                 "  **Files:**\n  - `apps/web/package.json`\n")
    proposals = plan_owner_tasks(published, published, ("apps/web",), ("apps/web",))
    assert len(proposals) == 1
    assert proposals[0].task_id == "T-002"
    assert proposals[0].contract_path == "apps/web/.echelon/runnability.yml"
    assert "req=INFRA depends=T-001 target=apps/web" in proposals[0].markdown
    assert "- [ ] T-002" in proposals[0].markdown

def test_existing_owner_or_valid_deferral_is_noop():
    tasks = ("## Summary\n\n- Total tasks: 1\n\n## Phase: Release\n"
             "- [ ] T-001 complexity=standard phase=release req=INFRA depends=none target=apps/web\n"
             "  **Files:**\n  - `apps/web/.echelon/runnability.yml`\n")
    assert plan_owner_tasks(tasks, tasks, ("apps/web",), ("apps/web",)) == ()
    no_owner = tasks.replace("apps/web/.echelon/runnability.yml", "apps/web/package.json")
    assert plan_owner_tasks(no_owner, no_owner, ("apps/web",), ()) == ()

def test_unrecognized_old_task_change_blocks_projection():
    old_tasks = ("## Summary\n\n- Total tasks: 1\n\n## Phase: Release\n"
                 "- [ ] T-001 complexity=standard phase=release req=INFRA depends=none target=apps/web\n"
                 "  **Files:**\n  - `apps/web/package.json` - original implementation\n")
    with pytest.raises(RunnabilityAmendmentPlanError, match="old task definition"):
        plan_owner_tasks(old_tasks, old_tasks.replace("original", "altered"), ("apps/web",), ("apps/web",))
```

  In the same file, add cases for duplicate ownership, malformed canonical rows, multiple required targets, next unused ID, and exact progress/status-only preservation using the same fully formed task rows.

- [ ] **Step 2: Run the new file and confirm red.** `.venv/bin/python -m pytest tests/unit/test_runnability_amendment_plan.py -q` must fail on the missing module/functions, not on test fixture syntax.
- [ ] **Step 3: Implement the pure planner.** Reuse `parse_task_rows` and `task_declares_file`; compare published and working old blocks after masking only recognized task, acceptance, and test checkbox progress plus canonical `Status` lines. Reject changed prose, paths, dependencies, or unrecognized status. Preserve the exact working old-block bytes when projecting; do not regenerate them with `update_task_progress_markdown`. Reserve IDs from all canonical rows and append the new task at the end; update only the Summary total count. Use this key branch:

```python
for target in required_targets:
    contract = (Path(target) / ".echelon/runnability.yml").as_posix()
    owners = [row.task_id for row in rows
              if (row.target or ".") == target
              and task_declares_file(published_tasks, row.task_id, contract)]
    if len(owners) > 1:
        raise RunnabilityAmendmentPlanError(f"ambiguous owner for {target}")
    if not owners:
        proposals.append(_new_pending_owner_task(target, contract, next_id, rows))
```

  `_new_pending_owner_task` is private to this file; render `req=INFRA`, the target's last canonical task as dependency (or `none` if no target task), exact `Files` contract path, and acceptance for a real composed install/start/readiness/primary-journey/stop flow. Do not choose commands or edit old task blocks.
- [ ] **Step 4: Run focused green and functional output check.** Run the test file and assert an actual proposal renders a valid canonical row via `validate_tasks_markdown`; inspect the full appended bytes in the test failure output if it differs.
- [ ] **Step 5: Commit only this pure slice.** `git add src/harness/runnability_amendment_plan.py tests/unit/test_runnability_amendment_plan.py`; `git commit -m 'feat(spec): plan missing runnability owner deterministically'`.

### Task 2: Isolated proposal and thin command routing

**Files:**
- Create: `src/echelon/runnability_amendment.py`
- Modify: `src/echelon/cli_app.py`, `src/echelon/spec_service.py`
- Test: `tests/unit/test_runnability_amendment.py`, `tests/unit/test_cli_typer_app.py`, `tests/unit/test_spec_service_boundary.py`

**Interfaces:**
- Consumes: Task 1 proposal, `resolve_control_baseline`, `create_amendment_worktree`, `AmendmentLock`, `PhaseAExecutionLock`, authoritative target stack resolution, and current readiness.
- Produces: `preview_runnability_owner(project_root: Path, spec_id: str) -> dict[str, object]` (read-only); `prepare_runnability_owner(project_root: Path, spec_id: str) -> dict[str, object]` (isolated proposal and amendment state). Existing `prepare_amendment` behavior is unchanged.

- [ ] **Step 1: Write failing CLI and real-repository tests.** In a temporary repo with a published spec branch and one selected required stack, assert preview returns the proposed ID/path but no worktree, ref, state, or file change; prepare creates an isolated amendment commit whose diff only appends the new task and count. Add a CLI test that `--runnability-owner --dry-run` delegates to the new service and `spec amend promote <id>` is recognized rather than treated as a generic product-input amendment. Reject `--input` combined with `--runnability-owner`.

```python
before = _git(repo, "rev-parse", "refs/heads/004-demo")
preview = preview_runnability_owner(repo, "004-demo")
assert preview["new_task_ids"] == ["T-002"]
assert _git(repo, "rev-parse", "refs/heads/004-demo") == before
assert not (repo / ".echelon/runtime/amend-worktrees/004-demo").exists()
```

- [ ] **Step 2: Run the named tests red.** Run `tests/unit/test_runnability_amendment.py` plus the two new CLI/service test names with `-q`; require a missing route or callable failure.
- [ ] **Step 3: Implement read-only preview, then isolated prepare.** Resolve required targets with the same stack/disposition/readiness inputs as Phase A, not a duplicate policy table. Require a published spec branch, no active Spec/Delivery operation or unsettled publication, and no unrecognized working edit. Acquire the per-spec mutation and Phase A execution locks only for prepare. Pin the old full-plan input hash from the published branch, then use `create_amendment_worktree`; write only the new plan task and amendment manifest in that isolated worktree, commit there, and record each target's source-repository identity and tentative candidate/checkpoint references. A target with no candidate records `null` and an empty list. `--dry-run` does not allocate revision state or create a worktree.

```python
def preview_runnability_owner(project_root: Path, spec_id: str) -> dict[str, object]:
    baseline = resolve_control_baseline(project_root, spec_id)
    inputs = _read_published_and_working_inputs(project_root, baseline)
    required_targets = _required_non_deferred_targets(project_root, inputs)
    proposals = plan_owner_tasks(inputs.published_tasks, inputs.working_tasks,
                                 inputs.targets, required_targets)
    return _preview_record(baseline, inputs, proposals)

def prepare_runnability_owner(project_root: Path, spec_id: str) -> dict[str, object]:
    with AmendmentLock.acquire(project_root, spec_id):
        with PhaseAExecutionLock.acquire(project_root, f"runnability-owner-{spec_id}"):
            preview = preview_runnability_owner(project_root, spec_id)
            return _write_isolated_proposal(project_root, preview)
```

  The three private helpers in this file read/validate inputs, apply the Task 1 proposal in the isolated worktree, and write the pinned manifest. They cannot write into the active checkout.
- [ ] **Step 4: Run focused green plus CLI functional check.** Execute the new tests and existing `tests/unit/test_spec_amendment.py`. In the disposable fixture, invoke `echelon.cli_app.app` through Typer's `CliRunner` with `spec amend 004-demo 'Add runnability owner' --runnability-owner --dry-run`; this uses the checkout under test, not the installed CLI. Verify identical Git status before and after dry-run.
- [ ] **Step 5: Commit this slice.** Stage only its listed files; `git commit -m 'feat(spec): prepare typed runnability amendment'`.

### Task 3: Recoverable promotion of file, index, and ref

**Files:**
- Create: `src/echelon/runnability_amendment_transaction.py`
- Modify: `src/echelon/runnability_amendment.py`, `src/echelon/spec_service.py`
- Test: `tests/unit/test_runnability_amendment_transaction.py`, `tests/unit/test_runnability_amendment.py`

**Interfaces:**
- Consumes: prepared amendment manifest/commit, pinned branch/ref, exact working-file preimage and projected hashes, index blob IDs, and `PublicationTransaction` for the working file.
- Produces: `promote_runnability_owner(project_root: Path, amendment_id: str) -> dict[str, object]`; `recover_runnability_promotion(project_root: Path, amendment_id: str) -> str`, returning `promoted`, `rolled_back`, or `needs_attention`. Delivery admission reads only `promoted`.

- [ ] **Step 1: Write fault-injection tests in real temporary Git repos.** Test the ordered cuts `before_file`, `after_file`, `after_index`, `after_ref`; require exact rollback before ref CAS and settlement after ref CAS. Add dirty unstaged progress, unrelated staged file, staged `tasks.md` rejection, ref race, index race, and an edit to projected `tasks.md` before recovery that yields `needs_attention` with the user's bytes untouched.

```python
assert _git(repo, "rev-parse", "HEAD") == old_commit
assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == old_index_blob
assert tasks_path.read_bytes() == old_progress_bytes
assert other_staged_path.read_bytes() == unrelated_bytes
```

- [ ] **Step 2: Run the transaction tests red.** `.venv/bin/python -m pytest tests/unit/test_runnability_amendment_transaction.py -q`; ensure each fault name reaches the intended cut, rather than failing in fixture setup.
- [ ] **Step 3: Implement the amendment-specific journal.** Record exact old/new branch commits, affected index blob IDs, working preimage/projected digests, current phase, and file-publication journal path. Under the same spec lock: verify active branch and preimages; install the projected working file with the existing publication primitive; update only affected index entries with `git update-index --cacheinfo`; verify index blobs; CAS `refs/heads/<spec_id>` from old to proposed commit last; mark promoted. Recovery follows the ref, not a stale phase flag:

```python
if current_ref == old_commit:
    rollback_exact_owned_file_and_index_or_mark_attention()
elif current_ref == proposed_commit:
    verify_exact_index_and_installed_file_or_mark_attention()
    mark_promoted_if_verified()
else:
    mark_needs_attention("branch moved outside amendment")
```

  The helper calls above are private functions in this file. They compare recorded digests before any write; no `git reset --hard`, broad checkout, or cleanup of unrelated files. After ref CAS, a subsequent user edit yields `needs_attention`, never an automatic rollback or overwrite. `spec_service` prints the exact status and blocks `delivery run` admission while unsettled.
- [ ] **Step 4: Run focused green and Git functional check.** Run transaction tests plus existing `test_promote_amendment_uses_compare_and_swap` and `test_promote_amendment_refuses_changed_canonical_branch`; inspect real temporary repo `HEAD`, index blob, working progress, and unrelated staged content after success and every fault cut.
- [ ] **Step 5: Commit this slice.** Stage only transaction and promotion files/tests; `git commit -m 'feat(spec): promote runnability amendment recoverably'`.

### Task 4: Target-local checkpoint carry-forward at Delivery admission

**Files:**
- Create: `src/harness/amendment_lineage.py`
- Modify: `src/harness/skills/run_skill.py`
- Test: `tests/unit/test_amendment_lineage.py`, `tests/unit/test_run_skill_checkpoint_recovery.py`

**Interfaces:**
- Consumes: settled promoted amendment manifest, current target identity, current spec input hash, native selected candidate, target-local delivery states, and `gitops.commit_is_ancestor`.
- Produces: `proven_amended_task_ids(manifest: Mapping[str, object], *, target_id: str, candidate: str | None, current_input_hash: str, states: Iterable[Mapping[str, object]], commit_is_ancestor: Callable[[str, str], bool]) -> tuple[str, ...]`. Raises `AmendmentLineageError` before dispatch for changed or unsettled lineage.

- [ ] **Step 1: Write failing lineage tests.** Use two target IDs and different candidate DAGs. Assert an accepted T-001 with matching old full-plan hash and ancestor checkpoint carries only for its target; a matching task ID with another hash or nonancestor commit does not. Assert checkbox/provider-result-only completion does not carry. Reject target identity change, changed older task definition, candidate mismatch, pending/unknown dispatch, unsettled promotion, and current hash different from manifest's new hash. Add a test that the existing exact-hash path still works unchanged when no promoted amendment exists.

```python
assert proven_amended_task_ids(manifest, target_id="apps/web",
    candidate=web_candidate, current_input_hash=new_hash,
    states=(accepted_web_state, accepted_api_state),
    commit_is_ancestor=is_ancestor) == ("T-001",)
```

- [ ] **Step 2: Run those tests red.** `.venv/bin/python -m pytest tests/unit/test_amendment_lineage.py -q` must fail because the new validator is absent.
- [ ] **Step 3: Implement a narrow admission branch.** Load only a manifest that names the current promoted spec commit and target; validate its settled transaction, old/new full-plan hashes, unchanged old task definitions, target repository, exact selected candidate, and original sealed-operation status. For each checkpoint, require its `checkpoint_input_hash == old_hash`, accepted `task_ids`, and `commit_is_ancestor(checkpoint_commit, candidate) is True`. Do not merge evidence across target run directories or treat `build.task_results` as acceptance. Return only proven IDs; do not rewrite old state. In `_execute_delivery_run`, call this after native baseline selection and before advancing the new current-build marker; when no applicable manifest exists, leave `_fresh_delivery_completed_tasks` and its strict current-hash behavior intact.

```python
if promoted_amendment is None:
    fresh_completed_task_ids = _fresh_delivery_completed_tasks(
        harness_root, intent, fresh_branch_base, gitops, spec_dir=spec_dir)
else:
    fresh_completed_task_ids = proven_amended_task_ids(
        promoted_amendment, target_id=target_id, candidate=fresh_branch_base,
        current_input_hash=checkpoint_input_hash(spec_dir),
        states=_target_delivery_states(harness_root, intent.spec_id),
        commit_is_ancestor=gitops.commit_is_ancestor)
```

  `promoted_amendment` is loaded from the control repository; `target_id` is the resolved current target; `_target_delivery_states` iterates this target's existing run directory only. Put these adapter helpers beside the existing fresh-run logic, not in the CLI.
- [ ] **Step 4: Run focused green and admission functional check.** Run both test files and an actual temporary target Git repo whose candidate contains one accepted checkpoint. Confirm only the new owner task is selected when old tasks are proven; remove one checkpoint and confirm the old task is no longer inherited. Confirm no provider invocation when lineage blocks.
- [ ] **Step 5: Commit this slice.** Stage only lineage, admission, and tests; `git commit -m 'feat(delivery): inherit amended-plan checkpoints by target'`.

### Task 5: Disposable native transition and preserved-workspace eligibility

**Files:**
- Test: `tests/integration/test_published_spec_runnability_amendment.py`
- Modify only if a reproducible harness defect is found: the file that owns that defect, with its own failing focused regression first.

**Interfaces:**
- Consumes: Tasks 1–4 CLI and harness behavior.
- Produces: one documented receipt showing preview, prepare, promote, fresh Delivery task selection, four independent reviews, and fresh final verification in a disposable workspace; then a read-only eligibility report for the preserved demo workspace.

- [ ] **Step 1: Write and run a disposable integration regression.** Create a temporary control repo with a published one-task Spec, required selected runnability stack, and a target repo with an accepted old-hash checkpoint. Invoke the same Spec service and Delivery admission functions the CLI uses. Assert promotion leaves old progress intact and Delivery selects only the new owner task. Use a deterministic fake provider for the four review results; do not make the assertion depend on a screenshot-update proposal counting as final acceptance.

```python
preview = preview_runnability_owner(control_repo, "004-demo")
assert preview["new_task_ids"] == ["T-002"]
prepared = prepare_runnability_owner(control_repo, "004-demo")
promoted = promote_runnability_owner(control_repo, prepared["amendment_id"])
assert promoted["status"] == "promoted"
assert "- [x] T-001" in tasks_path.read_text(encoding="utf-8")
assert "- [ ] T-002" in tasks_path.read_text(encoding="utf-8")
assert select_delivery_task(tasks_path.parent) == "T-002"
```

  Import `select_delivery_task` from `harness.delivery_slice`. The test must also run fresh Delivery admission with a deterministic provider and assert that its durable selected task ID is T-002; the direct selector assertion alone is not sufficient.
- [ ] **Step 2: Run this integration test and fix only its first reproducible harness failure.** Run `.venv/bin/python -m pytest tests/integration/test_published_spec_runnability_amendment.py -q`. If it fails, add a focused red regression in the owning module, make that green, rerun the integration test, and commit the narrow correction before proceeding.
- [ ] **Step 3: Run one native disposable CLI smoke.** Install this harness checkout into a disposable Echelon environment, run preview → prepare → inspect → promote → fresh Delivery against a disposable product repo. Record commands, amendment ID, old/new hashes, candidate SHA, checkpoint IDs, selected task, review receipts, and final status. Stop at the first harness failure; do not restart repeatedly or edit generated product code.
- [ ] **Step 4: Inspect the preserved workspace read-only.** Report per target whether its selected candidate, source repository identity, all twelve old task checkpoints, old hash, and absence of pending/unknown dispatch satisfy Task 4. Do not promote or resume that workspace until this report says precisely which tasks can be retained.
- [ ] **Step 5: Final verification and review.** Run the new focused tests, surrounding Spec/Delivery recovery tests, `bash scripts/bash/dry-run.sh`, and the repository verification planner once. Record the already-known `test_converges_within_3_outer_iterations` fixture failure separately if it persists; do not count it as evidence that this amendment works or fails. Run an independent branch review against the design and this plan. Do not declare Delivery reliable merely because these tests pass: native final receipts decide that. Commit the integration test and any narrow fixes separately; do not push or restart the preserved Delivery run without the user's next instruction.

## Self-review gate

- Every design section has an owning task: planning/preview (1–2), promotion/recovery (3), lineage (4), and native verification (5).
- Each step is independently testable; failures stop the sequence before the next code slice.
- The existing strict checkpoint path remains the default; the amendment exception requires a promoted, settled, target-bound record.
- No task authorizes modifying the preserved demo or rewriting existing Delivery journals.
