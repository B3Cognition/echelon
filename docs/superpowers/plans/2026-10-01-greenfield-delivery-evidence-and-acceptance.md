# Greenfield Delivery Evidence and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh native Spec→Delivery run reach final acceptance without copied documentation receipts, overlapping native controllers, or a documentation review deadlock at the staged-report boundary.

**Architecture:** Add one immutable identity to new controlled documentation journals and compare it at every controlled replay/proof boundary. Hold one target-local OS execution lease around the existing native Delivery adapter, and clarify the existing staged-report review contract without weakening its verifier or publication gate. Preserve all other evidence formats and the single Delivery controller.

**Tech Stack:** Python 3, `fcntl.flock` on the supported local macOS/POSIX runtime, existing `DeliverySliceJournal` and `StateStore`, pytest, native Echelon CLI.

**Spec:** `docs/superpowers/specs/2026-10-01-greenfield-delivery-evidence-and-acceptance-design.md`

## Global Constraints

- Do not edit generated product files, old Delivery state/journals, amendment manifests, or task checkboxes by hand.
- Do not reset runs, migrate old journals, use unknown-dispatch reconciliation, weaken independent review, or call an intermediate gate convergence.
- Keep `proven_amended_task_ids` pure: only accepted checkpoint commits grant task credit; documentation gives no task credit.
- New controlled documentation journals have exact `{build_id, delivery_run_id, spec_id, operation_id}` identity; old formats stay readable only for their existing supported replay behavior, never for terminal handoff.
- The target lease is a native entry-boundary exclusion mechanism, not a new persisted run state or CLI recovery rule; keep per-build state and per-operation journal locks.
- Stage the author's `report_markdown`; publish canonical Spec reports only after independent PASS plus deterministic gate PASS. Keep the subsequent final verification mandatory for convergence.
- Use the existing worktree and focused tests after each correction. Run the relevant integration suite once before a fresh disposable Spec→Delivery acceptance run.

## Review Focus

- A byte-for-byte valid terminal journal copied under another operation path must not authorize handoff or controlled replay (Tasks 1–2 tests).
- A legacy/unbound journal or a binding with one wrong build, run, Spec, or operation value must fail closed on new controlled paths (Tasks 1–2 tests).
- Two native commands for one target, including the prior check-to-marker race, must not overlap; contention must not advance its current-build marker (Task 3 tests).
- Unexpected exception or process death must release the lease, while two distinct target roots remain independent (Task 3 tests).
- Historical `documentation-impact-report-missing` feedback must not demand a forbidden canonical write; a genuinely invalid staged report must still FAIL and repair before publication (Task 4 tests).

---

### Task 1: Version and bind new controlled documentation journals

**Files:**
- Modify: `src/harness/delivery_documentation_contract.py:125-220` — strict v5 field/shape validation; retain v2/v4 validation.
- Modify: `src/harness/delivery_documentation.py:115-293` — create/replay and reviewed-checkpoint binding.
- Test: `tests/unit/test_delivery_documentation.py`
- Test: `tests/unit/test_delivery_documentation_checkpoint.py`

**Interfaces:**
- Consumes: `operation_binding: Mapping[str, str] | None` supplied only by controlled Ralph calls.
- Produces: `DeliveryDocumentationRunner.run(..., operation_binding: Mapping[str, str] | None = None)` and `reviewed_runnability_checkpoint(..., operation_binding: Mapping[str, str] | None = None)`; new journals use schema 5 with `operation_binding` and `rejected_reviews: []`.
- Exact keys: `build_id`, `delivery_run_id`, `spec_id`, `operation_id`; each is a nonempty string. When the argument is supplied, loaded journal identity must equal it before dispatch, replay, or checkpoint reuse. No fallback to inferred path or backup state.

- [ ] **Step 1: Write RED journal tests.** In `test_delivery_documentation.py`, call the fixture runner with `operation_id="docs-op"` and a four-field binding. Assert the journal has v5 and the same binding, replay dispatches no agent, and replacing any one field or removing the binding blocks before dispatch. Add a v2 journal replay test using the existing unbound direct-run fixture, but assert it cannot be replayed with a controlled binding. In the checkpoint test, assert a copied v5 journal with wrong expected binding cannot supply reviewed runnability.

```python
identity = dict(build_id="build-a", delivery_run_id="run-a",
                spec_id="001-slice", operation_id="docs-op")
result = runner.run(**paths, operation_id="docs-op", operation_binding=identity)
assert result.succeeded, result.reason
data = json.loads(next(paths["evidence_root"].rglob("journal.json")).read_text())
assert data["schema_version"] == 5
assert data["operation_binding"] == identity
assert runner.run(**paths, operation_id="docs-op", operation_binding=identity,
                  journal_required=True).succeeded
assert provider.steps == ["tech_writer", "docs_verifier"]
```

- [ ] **Step 2: Run RED.** `.venv/bin/python -m pytest tests/unit/test_delivery_documentation.py tests/unit/test_delivery_documentation_checkpoint.py -q`; expect the new keyword/field assertions to fail, not a fixture setup error.
- [ ] **Step 3: Implement the narrow v5 contract.** Add `OPERATION_BINDING_FIELDS` and validate exact key set, string types, and nonempty values only for v5. Run existing `rejected_reviews` validation for both v4 and v5. Build new controlled data with v5 identity and an empty rejected-review list. Before `on_journal_ready` and dispatch, reject a loaded journal unless its v5 identity exactly matches a supplied binding; reject a v5 journal on an unbound call. Keep direct legacy calls' current v2/v4 behavior. On malformed-review retry, set schema 4 only when upgrading v2; retain schema 5 and its immutable identity otherwise. Apply the same comparison before `reviewed_runnability_checkpoint` returns.

```python
OPERATION_BINDING_FIELDS = {"build_id", "delivery_run_id", "spec_id", "operation_id"}
if data["schema_version"] == 5:
    identity = data["operation_binding"]
    _require(isinstance(identity, dict) and set(identity) == OPERATION_BINDING_FIELDS
             and all(isinstance(v, str) and bool(v) for v in identity.values()),
             "invalid documentation operation binding")
if operation_binding is not None and (
        data["schema_version"] != 5
        or data["operation_binding"] != dict(operation_binding)):
    raise DeliverySliceError("delivery_reconciliation_required: documentation operation binding changed")
```

- [ ] **Step 4: Run GREEN and commit.** `.venv/bin/python -m pytest tests/unit/test_delivery_documentation.py tests/unit/test_delivery_documentation_checkpoint.py -q`; inspect v2/v4 and malformed-review retries. Stage the four Task 1 files and commit `fix(delivery): bind controlled documentation journals to operation identity`.

### Task 2: Thread exact identity through Ralph and terminal handoff

**Files:**
- Modify: `src/harness/ralph.py:2624-2800,3360-3390` — construct/pass identity to runner and reviewed checkpoint.
- Modify: `src/harness/terminal_documentation_handoff.py:50-125` — require v5 and exact state/path identity.
- Test: `tests/unit/test_terminal_documentation_handoff.py`
- Test: `tests/unit/test_run_skill_checkpoint_recovery.py`

**Interfaces:**
- Consumes: Task 1 `operation_binding` arguments and existing `state["run_id"]`, `self._build_id`, `self._spec_id`, and `operation["id"]`.
- Produces: a controlled documentation operation whose first journal and every replay/checkpoint proof use one unchanged identity; `prove_terminal_documentation_handoff` retains its signature and returns `(build_id, operation_id) | None` only for matching v5 evidence.

- [ ] **Step 1: Write RED integration regressions.** Update `terminal_handoff_case` to produce a v5 journal with exact fixture identity. Copy the complete valid journal bytes from `docs-op` to a second derived `other-op` journal path, change the state's operation pointer to `other-op`, persist that state, and assert proof returns `None`. Parametrize one wrong binding value at a time, plus an old v2/v4 terminal journal, pending/error receipts, changed candidate, and unchanged positive v5 case. In `test_run_skill_checkpoint_recovery.py`, assert the successful handoff still inherits only checkpoint-backed task IDs.

```python
original = json.loads(journal_path.read_text())
assert original["operation_binding"] == dict(
    build_id=build_dir.name, delivery_run_id=state["run_id"],
    spec_id=state["spec_id"], operation_id="docs-op")
copied = DeliverySliceJournal(journal_path.parent.parent, "other-op").path
copied.parent.mkdir(parents=True, exist_ok=True)
copied.write_bytes(journal_path.read_bytes())
state["delivery_slice_operation"]["id"] = "other-op"
(build_dir / "state" / "delivery.json").write_text(json.dumps(state))
assert _prove(terminal_handoff_case, state=state) is None
```

- [ ] **Step 2: Run RED.** `.venv/bin/python -m pytest tests/unit/test_terminal_documentation_handoff.py tests/unit/test_run_skill_checkpoint_recovery.py -q`; expect the copied-path negative to fail on current code.
- [ ] **Step 3: Wire the controlled identity once.** After Ralph has selected/validated `operation`, create the mapping below for documentation only, pass it in `runner_options`, and use the same values at final reviewed-checkpoint reuse. Do not add identity fields to Delivery state or task journals. In handoff proof, after strict `validate_journal`, compare `schema_version == 5` and `operation_binding` to values from the persisted blocked state and `build_dir.name`; reject mismatch before reading its terminal verdict. Keep all existing receipt, Git, candidate, source, and lock checks.

```python
operation_binding = {
    "build_id": self._build_id,
    "delivery_run_id": state["run_id"],
    "spec_id": self._spec_id,
    "operation_id": operation["id"],
}
runner_options["operation_binding"] = operation_binding
# In terminal proof, derive expected from persisted state and path, never from journal:
expected = dict(build_id=build_dir.name, delivery_run_id=run_id,
                spec_id=spec_id, operation_id=operation_id)
if data["schema_version"] != 5 or data["operation_binding"] != expected:
    return None
```

- [ ] **Step 4: Run GREEN and commit.** `.venv/bin/python -m pytest tests/unit/test_terminal_documentation_handoff.py tests/unit/test_run_skill_checkpoint_recovery.py tests/unit/test_delivery_documentation.py tests/unit/test_delivery_documentation_checkpoint.py -q`. Confirm the old-state and journal bytes remain unchanged by proof. Stage Task 2 files and commit `fix(delivery): prove exact documentation operation provenance`.

### Task 3: Exclude competing native Delivery commands per target

**Files:**
- Create: `src/harness/delivery_execution_lease.py` — small target-root OS lease.
- Modify: `src/harness/skills/run_skill.py:1338-1485` — acquire before baseline/admission, release after controller outcome/exception.
- Create: `tests/unit/test_delivery_execution_lease.py`
- Test: `tests/unit/test_run_skill_checkpoint_recovery.py`

**Interfaces:**
- Produces: `target_delivery_execution_lease(harness_root: Path) -> ContextManager[None]`; raises `DeliveryExecutionLocked` on nonblocking contention. `run_skill._execute_delivery_run` maps that to a clear `RunContextError` before marker write or provider dispatch.
- The lease file is under `runs_dir(harness_root)` with a fixed name, never under a build/operation directory; a process-death-released file may remain. It is not a state file.

- [ ] **Step 1: Write RED lease tests.** Verify second acquisition for one target raises immediately, including from a separate process; two roots acquire concurrently; an exception releases; killing a child that holds the lease allows a later acquisition. At the adapter boundary, pause the first controller between admission and marker reservation and try a second native adapter call: assert a clear contention result, no second marker advancement, and no second provider/controller construction. Test fresh and `intent.resume=True` through the same `_execute_delivery_run` boundary.

```python
with target_delivery_execution_lease(target_a):
    with pytest.raises(DeliveryExecutionLocked):
        with target_delivery_execution_lease(target_a):
            pass
    with target_delivery_execution_lease(target_b):
        pass
with target_delivery_execution_lease(target_a):
    pass
```

- [ ] **Step 2: Run RED.** `.venv/bin/python -m pytest tests/unit/test_delivery_execution_lease.py tests/unit/test_run_skill_checkpoint_recovery.py -q`; expect missing lease API or adapter contention assertions to fail.
- [ ] **Step 3: Implement one scoped POSIX lease.** Use `runs_dir(harness_root) / ".delivery-execution.lock"`; create runs dir, open with `O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW`, reject symlink/nonregular file via `fstat`, acquire `flock(LOCK_EX | LOCK_NB)`, and close FD in `finally`. On `EAGAIN`/`EWOULDBLOCK`, raise `DeliveryExecutionLocked`; let other OS errors surface. Wrap the *entire* existing `_execute_delivery_run` body by extracting it unchanged into `_execute_delivery_run_locked(...)`, and put the lease in the original wrapper so it encloses `_fresh_delivery_baseline`, handoff proof, marker reservation, controller `run`, and summary. Preserve existing `ExitStack` journal-lock scope inside that body.

```python
@contextmanager
def target_delivery_execution_lease(harness_root: Path):
    path = runs_dir(harness_root) / ".delivery-execution.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("unsafe delivery execution lease")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeliveryExecutionLocked("delivery already running for this target") from exc
        yield
    finally:
        os.close(fd)
```

- [ ] **Step 4: Run GREEN and commit.** `.venv/bin/python -m pytest tests/unit/test_delivery_execution_lease.py tests/unit/test_run_skill_checkpoint_recovery.py tests/unit/test_cli_delivery_recovery_safety.py -q`. Confirm no marker/provider side effect on contention and exception/process-death release. Stage Task 3 files and commit `fix(delivery): serialize native execution per target`.

### Task 4: Make staged documentation review explicit without relaxing gates

**Files:**
- Modify: `src/harness/delivery_documentation.py:315-410` — captured reviewer context and repair-feedback labeling.
- Modify: `prosaic/subagents/echelon.delivery-tech-writer.md` — returned report repair contract.
- Modify: `prosaic/subagents/echelon.delivery-docs-verifier.md` — staged report/publication order.
- Test: `tests/unit/test_delivery_documentation.py`
- Test: `tests/unit/test_delivery_documentation_checkpoint.py`

**Interfaces:**
- Consumes: writer's `report_markdown`, existing deterministic report, existing historical `feedback` and independent findings.
- Produces: reviewer prompt with the current exact staged impact text and explicit `publication_status="staged_not_published"`; writer repair prompt labels old feedback historical and directs report-content fixes into returned `report_markdown`. Receipt/gate/publication interfaces do not change.

- [ ] **Step 1: Write RED behavioral tests.** Use the `documentation_project` executor to inspect actual writer/reviewer prompts. Supply historical feedback containing `documentation-impact-report-missing` and assert the reviewer receives staged impact text plus explicit unpublished status; the writer receives explicit instruction not to create a canonical Spec report. Script a first malformed impact report and verifier `FAIL`, then a corrected returned report and verifier `PASS`; assert canonical report snapshots remain absent during all agent calls and the exact corrected returned reports appear only after PASS. A permanently malformed report must remain blocked with its source-backed finding.

```python
reviewer_prompt = next(prompt for assignment, _, prompt in provider.calls
                       if assignment["step"] == "docs_verifier")
assert '"publication_status": "staged_not_published"' in reviewer_prompt
assert '"impact_report"' in reviewer_prompt
assert provider.snapshots == [None] * len(provider.calls)
assert (paths["spec_dir"] / "documentation-impact-report.md").read_text() == corrected_impact
```

- [ ] **Step 2: Run RED.** `.venv/bin/python -m pytest tests/unit/test_delivery_documentation.py tests/unit/test_delivery_documentation_checkpoint.py -q`; expect the new context/repair assertions to fail.
- [ ] **Step 3: Add only context and role wording.** In reviewer `review_context`, include `publication_status`, `impact_report_source="writer_result.report_markdown"`, and a sentence that canonical report absence is expected until PASS; retain the full staged text and deterministic baseline. In `repair_feedback`, label incoming `feedback` as historical, keep fresh independent/deterministic/gate findings as current, and direct writer fixes to returned report text. Amend both role files' ALWAYS/NEVER rules to distinguish staged text from canonical publication. Do not modify verdict mapping, deterministic gate logic, `verify_docs`, or publication transaction.

```python
review_context = {
    "impact_report": impact,
    "impact_report_source": "writer_result.report_markdown",
    "publication_status": "staged_not_published",
    "deterministic_baseline": _report_markdown(deterministic),
}
# Existing historical feedback remains visible; it is not current evidence
# that the staged report is absent or permission to write into spec_dir.
```

- [ ] **Step 4: Run GREEN and commit.** `.venv/bin/python -m pytest tests/unit/test_delivery_documentation.py tests/unit/test_delivery_documentation_checkpoint.py -q`. Inspect a real scripted FAIL→repair→PASS and a persistent FAIL; assert independent reviewer and deterministic gate still decide publication. Stage Task 4 files and commit `fix(delivery): review staged documentation before canonical publication`.

### Task 5: One repository gate and one fresh native acceptance journey

**Files:**
- No product-code changes in this task; record command/results and durable evidence in `docs/superpowers/plans/2026-10-01-greenfield-delivery-evidence-and-acceptance.md` under the execution record below.

**Interfaces:**
- Consumes: Tasks 1–4 committed corrections and a *new* disposable Echelon workspace with a normal stack selection.
- Produces: exact command log, build IDs, receipt paths, and an evidence-backed terminal status. Intermediate passes are recorded as intermediate, not convergence.

- [ ] **Step 1: Run the combined focused gate.** `.venv/bin/python -m pytest tests/unit/test_delivery_documentation.py tests/unit/test_delivery_documentation_checkpoint.py tests/unit/test_terminal_documentation_handoff.py tests/unit/test_delivery_execution_lease.py tests/unit/test_run_skill_checkpoint_recovery.py tests/unit/test_cli_delivery_recovery_safety.py -q`; expect PASS. Then run the repository suite once with `.venv/bin/python -m pytest tests/unit -q -x`; record exact count and first failure, distinguishing the known `test_converges_within_3_outer_iterations` fixture failure from a new regression. Do not turn unrelated known failure into a claim of full-suite PASS.
- [ ] **Step 2: Prepare a *new* disposable target through ordinary CLI.** Run the commands below in a shell. The explicit `browser-threejs-npm` stack is a normal verification-capable stack; `generic` is discovery-only. Preserve the chosen root in the execution record. Do not copy old journals, edit generated application files, or hand-edit Delivery state.

```bash
acceptance_root=$(mktemp -d /tmp/echelon-delivery-acceptance-XXXXXX)
cd "$acceptance_root"
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/echelon workspace init --llm codex
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/echelon stack select browser-threejs-npm
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/echelon stack selected
```

- [ ] **Step 3: Run native Spec then Delivery.** Execute the concrete small browser request below. Confirm `spec status` reports published; if Phase A stops before publication, record its exact boundary instead of running Delivery. Derive `spec_id` from the only newly created canonical Spec directory and compare it with CLI output. The subsequent Delivery command uses that exact ID. Do not restart or raise caps merely to conceal a failure.

```bash
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/echelon spec run --mode banzai --init --target sources/demo "Build a small Three.js page showing a rotating colored cube, with a working local start command and one automated smoke test."
spec_id=$(find specs -mindepth 1 -maxdepth 1 -type d -name '[0-9]*' -print | sort | tail -1 | xargs basename)
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/echelon spec status
/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff/.venv/bin/echelon delivery run "$spec_id" --mode semi --max-outer 5 --max-inner 5 --token-budget 50000000 --no-auto-merge
```
- [ ] **Step 4: Inspect durable acceptance, not just stdout.** For the resulting build, read `state/delivery.json`, task-slice and documentation journals, runnability receipt, published impact and verification reports, and final verification evidence. Require checkpoint-backed task progress, current runnability, independent writer/verifier receipts, canonical publication after PASS, final verification PASS, and terminal `converged`. If the first new reproducible harness failure occurs, preserve the workspace and receipt, stop, diagnose that boundary separately, and return to a focused RED→GREEN test before attempting another native run.
- [ ] **Step 5: Close only on evidence.** Add exact commands, counts, receipt paths, and status to the execution record. Commit only that record if acceptance converged; otherwise report the precise boundary reached and leave this task unchecked. Request whole-branch review before any merge or push.

## Execution record

This section is intentionally blank until Task 5 executes. Record the new workspace path, Spec and build IDs, focused and repository test outcomes, exact journal/report paths, and terminal status here. A blocked run is a recorded outcome, not completion.
