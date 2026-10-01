# Terminal Documentation Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admit a fresh amended Delivery run after a provably terminal failed documentation operation, without granting documentation or task credit from that operation.

**Architecture:** Keep `proven_amended_task_ids` pure and fail-closed; it accepts only a caller-proven `(build_id, operation_id)` exemption for a documentation pointer. A small admission helper proves the old journal's terminal receipt, state binding, exclusive lock, and exact clean salvage bytes. The run adapter holds the journal lock through new-build reservation, then runs ordinary Delivery gates.

**Tech Stack:** Python 3, existing `DeliverySliceJournal`, Git CLI, pytest, native Echelon Delivery CLI.

**Spec:** `docs/superpowers/specs/2026-10-01-terminal-documentation-handoff-design.md`

## Global Constraints

- Do not edit generated demo files, old Delivery state/journals, the amendment manifest, or task checkboxes during admission.
- Do not use reset, unknown-dispatch reconciliation, a CLI-specific repair rule, or weaker review/verification gates.
- Only checkpoint commits authorize old task progress; a terminal documentation verdict authorizes no progress.
- Preserve the existing exact-hash Delivery path and the default rejection of pending or unknown operations.
- Use the existing branch/worktree; do not create another checkout for this implementation.

## Review Focus

- A journal with a pending or error receipt must still block before a new build marker (Task 2 negative cases; Task 3 adapter test).
- A terminal-looking journal copied to another build or operation ID must not authorize handoff (Task 2 identity/path test).
- A committed but changed candidate, including ignored document bytes, must not pass the fingerprint proof (Task 2 candidate test).
- A live old state owner or locked journal must not race a fresh run (Task 2 lock tests; Task 3 lock-scope test).
- A valid docs verdict with no accepted checkpoint must not create task credit (Task 1 pure test; Task 3 adapter test).

---

### Task 1: Pure lineage accepts only explicitly proven terminal documentation identities

**Files:**
- Modify: `src/harness/amendment_lineage.py:27-115`
- Test: `tests/unit/test_amendment_lineage.py`

**Interfaces:**
- Consumes: existing `states` with `build_id` and `delivery_slice_operation`.
- Produces: optional keyword-only `terminal_documentation_handoffs: frozenset[tuple[str, str]] = frozenset()` on `proven_amended_task_ids`.

- [ ] **Step 1: Write a failing pure regression.** Add a state with `kind=documentation`, `id=docs-op`, `progress_applied=False`. Assert the default call still raises; with `{("build-web", "docs-op")}` it returns only checkpoint-proven `T-001`. Parametrize wrong ID, wrong build, task kind, and a second unresolved state to assert each still raises. Add a no-checkpoint case that returns `()` even with the matching proof.

```python
docs = _state("apps/web", "build-web", WEB_CHECKPOINT, "T-001")
docs["delivery_slice_operation"] = {
    "kind": "documentation", "id": "docs-op", "progress_applied": False,
}
with pytest.raises(AmendmentLineageError, match="pending Delivery operation"):
    _prove(_manifest(), (docs,))
assert proven_amended_task_ids(
    _manifest(), target_id="apps/web", candidate=WEB_CANDIDATE,
    current_input_hash=NEW_HASH, states=(docs,),
    commit_is_ancestor=lambda a, b: (a, b) == (WEB_CHECKPOINT, WEB_CANDIDATE),
    terminal_documentation_handoffs=frozenset({("build-web", "docs-op")}),
) == ("T-001",)
```

- [ ] **Step 2: Run the new test RED.** Run `.venv/bin/python -m pytest tests/unit/test_amendment_lineage.py -q`; expect failure from the absent keyword, not from test setup.
- [ ] **Step 3: Implement the smallest pure change.** Add the optional parameter. In the existing pending-operation loop, continue only if `pending.get("kind") == "documentation"`, `pending.get("id")` is a nonempty string, and the exact pair is in the supplied frozen set. Leave every other branch of checkpoint proof unchanged.

```python
if (pending.get("kind") == "documentation"
        and isinstance(pending.get("id"), str) and pending["id"]
        and (build_id, pending["id"]) in terminal_documentation_handoffs):
    continue
raise AmendmentLineageError(
    f"pending Delivery operation in {build_id}; recover it under sealed inputs"
)
```

- [ ] **Step 4: Run the whole lineage file GREEN.** Run `.venv/bin/python -m pytest tests/unit/test_amendment_lineage.py -q`; confirm all existing pending-dispatch negatives pass.
- [ ] **Step 5: Commit this independently testable contract.** Stage only the two Task 1 files; commit `fix(delivery): require explicit terminal docs lineage proof`.

### Task 2: Prove the terminal journal and exact retained candidate

**Files:**
- Create: `src/harness/terminal_documentation_handoff.py`
- Create: `tests/unit/test_terminal_documentation_handoff.py`

**Interfaces:**
- Consumes: a target-local old state, its resolved `build_dir`, current `spec_dir`, the selected candidate SHA, and the expected amendment-admission identity.
- Produces: `prove_terminal_documentation_handoff(*, state: Mapping[str, object], build_dir: Path, spec_dir: Path, candidate: str, amendment_identity: Mapping[str, str], lock_stack: ExitStack) -> tuple[str, str] | None`. A successful call leaves the existing journal lock on `lock_stack` until its owner exits. Failure returns `None` and does not grant authority.

- [ ] **Step 1: Create a real terminal fixture and failing positive test.** Reuse `documentation_project`; copy its project into `build_dir/worktrees/iter-0` and use the original external `spec_dir`, so the operation path is genuinely inside its build. Initialize/commit that worktree before dispatch. Execute a writer returning `NEEDS_CONTEXT` with known usage, with `operation_id="docs-op"` and evidence root `build_dir/state/delivery-slices/sha256(f"{build_id}:{run_id}")`. Commit the writer's allowed README/CHANGELOG output as salvage, and construct state with the exact blocked reason, `amendment_admission`, `run_id`, and operation path. Make a `terminal_handoff_case` fixture returning `(state, journal_path, worktree, spec_dir, salvage_commit, build_dir, identity)`. Assert the helper returns `(build_id, "docs-op")`, the journal remains unchanged, and `lock_stack.close()` releases its lock.

```python
def terminal_writer(assignment, payload, _root):
    if assignment["step"] == "tech_writer":
        payload.update(verdict="NEEDS_CONTEXT", summary="need context", findings=["source-backed gap"])
    return CliRunResult(0, json.dumps(payload), "", token_usage=7)

with ExitStack() as locks:
    assert prove_terminal_documentation_handoff(
        state=blocked_state, build_dir=build_dir, spec_dir=spec,
        candidate=salvage_commit, amendment_identity=identity,
        lock_stack=locks,
    ) == (build_dir.name, "docs-op")
```

- [ ] **Step 2: Run that test RED.** Run `.venv/bin/python -m pytest tests/unit/test_terminal_documentation_handoff.py -q`; expect the missing helper/import, not a malformed fixture.
- [ ] **Step 3: Implement the proof helper.** Check exact blocked state and amendment identity, no live `delivery.lock` owner, a safe operation worktree under `build_dir/worktrees`, exact clean Git HEAD equal to `candidate == salvage_commit`, and an existing journal at the run-ID/operation-ID derived path. Enter `DeliverySliceJournal(root, operation_id, validator=validate_journal)` on `lock_stack` and `load(required=True)`. Require `publication is None`, a final completed `BLOCKED`/`NEEDS_CONTEXT` result with no error, known usage for all normal and rejected receipts, exact state reason `delivery_documentation_{step}_blocked: {summary}`, and fresh `_documentation_candidate_fingerprint`/`_source_fingerprint` equality. Catch only expected validation, filesystem, lock, and Git failures; return `None` on failed proof. Do not write state or journal content.

```python
root = build_dir / "state" / "delivery-slices" / hashlib.sha256(
    f"{build_dir.name}:{state['run_id']}".encode()
).hexdigest()
journal = DeliverySliceJournal(root, operation_id, validator=validate_journal)
if not journal.path.is_file():
    return None
loaded = lock_stack.enter_context(journal).load(required=True)
last = loaded["records"][-1]
if (last["error"] is not None or last["result"] is None
        or last["result"]["verdict"] not in {"BLOCKED", "NEEDS_CONTEXT"}):
    return None
```

- [ ] **Step 4: Add fail-closed mutations one at a time.** Parametrize missing/wrong-path journal, malformed or pending last receipt, provider error, `FAIL`/`PASS`, unknown usage, mismatched reason/admission, wrong build or operation ID, live state lock, journal lock contention, dirty or changed worktree, wrong salvage SHA, changed ignored README, and changed source fingerprint. Each must return `None` without the proof helper altering state or journal beyond the test's deliberate mutation. A valid `BLOCKED` docs-verifier receipt is an additional positive case. Use the `terminal_handoff_case` tuple from Step 1; apply one explicit mutation per case before calling the helper.

```python
def test_unknown_usage_cannot_authorize_handoff(terminal_handoff_case):
    state, journal_path, worktree, spec, candidate, build_dir, identity = terminal_handoff_case
    data = json.loads(journal_path.read_text())
    data["records"][-1]["token_usage"] = None
    journal_path.write_text(json.dumps(data))
    with ExitStack() as locks:
        assert prove_terminal_documentation_handoff(
            state=state, build_dir=build_dir, spec_dir=spec,
            candidate=candidate, amendment_identity=identity, lock_stack=locks,
        ) is None
```

- [ ] **Step 5: Run focused helper and documentation journal tests GREEN.** Run `.venv/bin/python -m pytest tests/unit/test_terminal_documentation_handoff.py tests/unit/test_delivery_documentation.py -q`; inspect every failure rather than loosening schema checks.
- [ ] **Step 6: Commit the proof unit.** Stage only Task 2 files; commit `fix(delivery): prove terminal documentation handoff from retained receipts`.

### Task 3: Wire proof into fresh amended admission and reserve the new build safely

**Files:**
- Modify: `src/harness/skills/run_skill.py:429-690,1320-1370`
- Test: `tests/unit/test_run_skill_checkpoint_recovery.py`

**Interfaces:**
- Consumes: Task 2 `prove_terminal_documentation_handoff` and Task 1 `terminal_documentation_handoffs` parameter.
- Produces: unchanged `_AmendedDeliveryAdmission` result; only its internal admission may carry explicit terminal identities.

- [ ] **Step 1: Write failing adapter regression.** Extend the real amended-target fixture in `test_run_skill_checkpoint_recovery.py` with an admitted blocked documentation state and Task 2's actual terminal journal fixture. Assert `_amended_delivery_completed_tasks` returns only accepted checkpoint IDs, not the docs result; `_execute_delivery_run` reaches the new run without resetting or rewriting the old state. For an unknown or task operation, assert `RunContextError` before `current_build_marker` exists or changes.

```python
with ExitStack() as admission_locks:
    admitted = _amended_delivery_completed_tasks(
        workspace_root=repo, harness_root=harness_root, spec_dir=spec,
        intent=intent, candidate=salvage_commit, gitops=gitops, config=config,
        handoff_locks=admission_locks,
    )
    assert admitted.task_ids == ("T-001",)
    assert json.loads(old_state_path.read_text())["delivery_slice_operation"]["progress_applied"] is False
```

- [ ] **Step 2: Run adapter test RED.** Run `.venv/bin/python -m pytest tests/unit/test_run_skill_checkpoint_recovery.py -q`; expect the missing adapter parameter/proof wiring.
- [ ] **Step 3: Implement narrow wiring.** Add optional `handoff_locks: ExitStack | None` to `_amended_delivery_completed_tasks`. For each matching target state with an unapplied documentation operation, call Task 2's helper using the exact state-derived build directory, selected candidate, canonical spec, and current amendment identity; collect only successful identity pairs. Pass the frozen set to `proven_amended_task_ids`. In `_execute_delivery_run`, hold an `ExitStack` across fresh baseline selection, amended admission, recovered-task computation, and `current_build_marker.write_text(build_id)`; then release it before ordinary controller execution. Direct admission callers use a local stack that closes on return. Do not alter resume admission or non-amended exact-hash recovery.

```python
with ExitStack() as admission_locks:
    fresh_branch_base = None if intent.resume else _fresh_delivery_baseline(harness_root, intent, gitops)
    amended_completed = _amended_delivery_completed_tasks(
        workspace_root=workspace_root, harness_root=harness_root,
        spec_dir=spec_dir, intent=intent, candidate=fresh_branch_base,
        gitops=gitops, config=config, resume_build_id=resume_build_id,
        handoff_locks=admission_locks,
    )
    # Indent the existing completed-task, repair-task, and marker statements
    # into this scope without changing their expressions or order.
```

- [ ] **Step 4: Add lock-scope and no-credit assertions.** While admission holds the stack, a second `DeliverySliceJournal` open for the old operation must raise `delivery_slice_locked`; after the new marker is reserved, the lock must release. Delete the accepted checkpoint from a fixture and assert no task is inherited even though the docs handoff proves terminal.
- [ ] **Step 5: Run focused adapter, lineage, and recovery tests GREEN.** Run `.venv/bin/python -m pytest tests/unit/test_run_skill_checkpoint_recovery.py tests/unit/test_amendment_lineage.py tests/unit/test_terminal_documentation_handoff.py tests/unit/test_cli_delivery_recovery_safety.py -q`. Run `.venv/bin/python -m pytest tests/unit/test_delivery_documentation_checkpoint.py -q` separately; do not confuse the known unrelated full-suite fixture failure with this work.
- [ ] **Step 6: Commit the admission slice.** Stage only Task 3 files; commit `fix(delivery): admit settled documentation handoff before new build`.

### Task 4: One native disposable continuation and evidence review

**Files:**
- Read-only inspection: `echelon-amend-smoke.W7oLXM/runs/targets/web/runs/*/state/delivery.json` and operation journals.
- No product or state edits; no code commit unless a new harness defect is independently diagnosed and separately scoped.

**Interfaces:**
- Consumes: committed Tasks 1–3 installed into the disposable workspace's Echelon environment.
- Produces: an observed native admission/Delivery outcome, not an inferred success.

- [ ] **Step 1: Verify the preflight snapshot.** Confirm harness checkout clean; old build blocked with the exact terminal documentation receipt; salvage worktree clean at `da8b016b581e`; no Delivery process active. Record the current build marker and Spec/target status without writing to them.
- [ ] **Step 2: Confirm the disposable CLI uses the committed checkout.** The existing `.venv` is editable; run the command below and require the printed path to be this worktree's `src/echelon/__init__.py`. The native Delivery command refreshes the workspace Prosaic bundle. Do not install into another environment or edit the workspace by hand.

```bash
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/python -c 'import echelon; print(echelon.__file__)'
```

- [ ] **Step 3: Run one fresh native command, without reset or reconciliation.** From `/Users/michalbachorik/work/echelon_r/echelon-amend-smoke.W7oLXM`:

```bash
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/echelon delivery run 004-smoke --mode semi --max-outer 3 --max-inner 3 --token-budget 2000000 --no-auto-merge
```

- [ ] **Step 4: Inspect durable evidence.** Confirm selected candidate and inherited checkpoint IDs, distinct new documentation author/reviewer receipts, refreshed runnability, final verification, and terminal Delivery status. A terminal docs proof or passing journey alone is not convergence. Stop at the first new reproducible harness failure; report its exact state/journal evidence before proposing another fix.
- [ ] **Step 5: Report status.** State what passed, what blocked, and whether the original amended admission failure recurred. Do not edit generated demo code, delivery state, or reviewer gates to manufacture progress.
