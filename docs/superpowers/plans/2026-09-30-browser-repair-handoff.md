# Browser Repair Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the selected native execution method. Steps use checkbox (`- [ ]`) syntax for tracking. Execute Task 1 first and report its functional results before advancing to Task 2.

**Goal:** Repair a browser failure under its actual task owner, then return to the interrupted task without losing evidence, acceptance gates, or consumed allowances.

**Architecture:** Ralph retains sole ownership of the active operation in `delivery_slice_operation`. The task runner exposes authenticated browser failures and explicit controller checkpoints; linked journals explain owner repair and return without rewriting provider receipts. This is one handoff, not a recursive scheduler or a new agent.

**Tech Stack:** Existing Python dataclasses, atomic JSON files, `DeliverySliceJournal`, `StateStore`, pytest, and the existing Docker browser-capture runtime. No new dependency.

**Spec:** [Approved design](../specs/2026-09-30-browser-repair-handoff-design.md).

## Global Constraints

- “No new agent, general workflow engine, recursive repair stack, manual demo changes, gate exemptions, counter resets, or automatic increases to configured limits.”
- “`delivery_slice_operation` remains the single persisted active-operation authority.”
- “Original dispatch records and receipts remain unchanged.”
- “The returned task obtains its own fresh, task-bound capture even if the repair recheck used the same unchanged candidate.”
- “A passing handoff is not final Delivery acceptance.”
- Preserve `MAX_GATE_ROUNDS = 5`, `MAX_BROWSER_REQUESTS = 4`, and `MAX_BROWSER_REPAIR_REQUESTS = 2`. Continuations inherit consumed allowances; they do not start at zero.
- Keep `DeliveryController` and CLI admission policies unchanged unless a functional test proves the native continuation cannot reach the new controller-owned recovery. Report such a blocker before expanding the plan.
- Version 2 receipts/journals stay immutable. Their diagnostic prose is never routing authority.
- Work in `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff`, branch `fix/browser-evidence-handoff`. Do not create another worktree or edit the generated demo.
- Every implementation task follows red → green → focused functional verification → local commit. No push is included.

## Review Focus

1. Changed spec, scope, or role inputs between pause and return must reject the continuation before dispatch (Tasks 1, 3).
2. Missing, redirected, or modified predecessor/capture files must block without guessing an owner or creating replacement authority (Tasks 1, 4).
3. A provider overshoot or exhausted capture allowance must leave no fresh allowance available on restart (Tasks 2, 4).
4. Process loss after receipt persistence but before active-operation/accounting persistence must not repeat completed effects or charges (Tasks 3, 4).
5. Owner reviews can pass while the original browser command still fails; that must trigger a bounded owner repair, not source-task acceptance or a third-task recursion (Tasks 2, 3).

## Files and responsibility

| File | Responsibility |
| --- | --- |
| Create `src/harness/delivery_browser_handoff.py` | Handoff-specific types, deterministic IDs, authenticated predecessor/receipt checks, continuation allowance derivation. No state writes, agent dispatch, or general workflow abstraction. |
| Modify `src/harness/delivery_slice.py` | Share existing strict failure-owner resolution without changing the accepted-task requirement for foreign source repair. Same-task implementation failures need no foreign-repair eligibility. |
| Modify `src/harness/build_result.py` | One optional typed browser-repair request; a request is never a successful build. Use a type-only import to avoid adding an import cycle. |
| Modify `src/harness/delivery_slice_journal.py` | Explicit current continuation/checkpoint schema and validation; retain unchanged version 2 validation. |
| Modify `src/harness/delivery_slice_runner.py` | Capture intents/results, typed yield, bounded post-review recheck, and continuation entry. |
| Modify `src/harness/ralph.py` | Persist selected owner/return operations and account usage once through existing controlled-slice boundaries. |
| Create `tests/unit/test_delivery_browser_handoff.py` | Real receipt/journal authentication and allowance tests. |
| Create `tests/unit/test_delivery_browser_handoff_execution.py` | Actual Ralph/runner execution with only provider/browser boundaries scripted. |
| Modify `tests/unit/test_delivery_slice_recovery.py` | Durable-boundary interruption tests using existing `ProcessLost`. |
| Modify this plan and `docs/simplification-control.md` | Record each tested checkpoint without declaring STAB-1 complete. |

Read `AGENTS.md`, the approved design, `delivery_slice_journal.py`, and the runner's existing `_supersede_failed_dispatch` before implementation. The latter is a write-order reference only: do not route completed browser requests through unknown-dispatch recovery.

## Task 1: Authenticate a handoff request and its continuation lineage

**Deliverable:** A small read-only contract that proves which operation/dispatch/candidate produced the failure and derives remaining allowances. No runtime routing change yet.

**Files:** Create `delivery_browser_handoff.py` and `test_delivery_browser_handoff.py`; modify `delivery_slice.py` for the shared ownership boundary and `build_result.py` for its optional typed field.

**Interfaces:** Define these types in the new module. A journal reference is resolved beneath the supplied evidence root using the existing SHA-256 operation-directory convention, never by accepting a caller-supplied journal path.

```python
@dataclass(frozen=True)
class JournalRef:
    operation_id: str
    journal_sha256: str

@dataclass(frozen=True)
class BrowserRepairRequest:
    source: JournalRef
    dispatch_id: str
    receipt: BrowserBaselineEvidenceRef

@dataclass(frozen=True)
class ContinuationAllowance:
    repair_attempt: int
    browser_requests_in_round: int
    tokens_consumed: int
    usage_known: bool
    token_limit: float | None

def handoff_operation_id(request: BrowserRepairRequest, stage: str) -> str:
    if stage not in {"owner", "refresh", "return"}:
        raise DeliverySliceError("invalid browser handoff stage")
    payload = {
        "source_operation": request.source.operation_id,
        "source_journal": request.source.journal_sha256,
        "dispatch": request.dispatch_id,
        "receipt": request.receipt.receipt_sha256,
        "stage": stage,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
```

Also define these public function interfaces:

- `resolve_browser_repair(request: BrowserRepairRequest, *, evidence_root: Path, spec_dir: Path, candidate_fingerprint: str, input_fingerprint: str, allowed_task_ids: set[str] | None) -> str`
- `continuation_allowance(journal: dict, *, token_limit: float | None) -> ContinuationAllowance`

`resolve_browser_repair` loads and validates the referenced journal, checks its digest and the completed originating browser request, verifies the exact attached receipt reference, and reads the receipt with source task/input/current-product bindings. The caller separately enforces the runner's full candidate fingerprint, including protected inputs. Failures use `DeliverySliceError`; neither method mutates files.

Extract `resolve_delivery_failure_owner(spec_dir: Path, feedback: dict, allowed_task_ids: set[str] | None) -> dict[str, object]` from the existing selector's strict identity/scope/unique-owner checks in `delivery_slice.py`. Keep `select_delivery_repair_task` as that resolution plus its existing accepted-task check. The browser resolver then uses:

```python
feedback = {"failures": observation.verification_failures}
selection = resolve_delivery_failure_owner(spec_dir, feedback, allowed_task_ids)
if selection["task_id"] == journal_data["task_id"]:
    return selection["task_id"]  # normal same-task repair, including a PENDING task
return select_delivery_repair_task(spec_dir, feedback, allowed_task_ids)["task_id"]
```

This preserves initial implementation's same-task repair behavior. It does not make a PENDING foreign task eligible for handoff or relax any unidentified/mixed-owner checks.

`continuation_allowance` derives the current round and capture consumption from validated records/checkpoints, sums known provider usage, retains whether usage is fully known, and takes the stricter saved/current token limit. Unknown usage under a finite budget, negative/non-finite limits, or inconsistent record order is an error. Unlimited-budget history must still retain `usage_known=False` rather than claiming unknown spending was zero. A returned allowance is derived evidence, not a writable budget ledger.

- [ ] **1. Write failing tests using real fixtures.** Import `slice_project`, `ScriptedExecutor`, and `_run` from `test_delivery_slice_runner`; import `_capture` and `_tasks` from `test_browser_capture_failures`. Use `_tasks` to declare both accepted owners. Produce a T-011 journal with `_run(slice_project, executor, repair_task_id="T-011", operation_id="source-op", browser_baseline_capture=capture, stop_requested=lambda: stop)`, one `BROWSER_EVIDENCE_REQUIRED` response, and a stop flag set by its capture callback. Build `BrowserRepairRequest` from that real journal and retained receipt. Assert these outcomes:

```python
assert resolve_browser_repair(request, **bindings) == "T-012"
assert source_journal_path.read_bytes() == original_journal_bytes
assert receipt.path.read_bytes() == original_receipt_bytes
assert not BuildResult(
    exit_code=1, status="browser_repair_required", impasse_file=None,
    stdout="", stderr="", duration_ms=0, browser_repair_request=request,
).succeeded
assert handoff_operation_id(request, "owner") == handoff_operation_id(request, "owner")
assert handoff_operation_id(request, "owner") != handoff_operation_id(request, "return")
```

Use the exact `BrowserBaselineEvidenceRef` already on the completed dispatch. Independently hard-code expected usage from scripted seven-token responses; do not compute expectations with `continuation_allowance` itself.

- [ ] **2. Add refusal cases.** Parameterize stale candidate/input, excluded T-012, unaccepted T-012, mixed owners, untagged failures, missing/symlinked journal, wrong dispatch/reference, changed digest, and version 2 receipt without structured failures. Assert `DeliverySliceError`, unchanged bytes, and zero further provider calls. Separately prove that an initial PENDING task's own tagged failure resolves to itself while an unaccepted foreign owner is rejected. Test unknown token usage and finite-budget overshoot explicitly.
- [ ] **3. Run RED.** `.venv/bin/python -m pytest tests/unit/test_delivery_browser_handoff.py -q`; confirm failure is due to missing contract behavior, not a broken fixture.
- [ ] **4. Implement the contract.** Add exact-field mapping validation for persisted references, use `DeliverySliceJournal.load(required=True)` and existing browser receipt validation, and reuse `select_delivery_repair_task`. Add `browser_repair_request: BrowserRepairRequest | None = None` to `BuildResult`; leave `succeeded` unchanged. Keep lineage validation outside CLI/provider prose.
- [ ] **5. Run GREEN and compatibility checks.** Run the new file plus `test_browser_capture_failures.py`, `test_browser_baseline_evidence.py`, and `test_delivery_repair_ownership.py`. A valid request resolves to T-012 without touching the candidate, progress, or active operation.
- [ ] **6. Commit and report this boundary.** Commit as `feat(delivery): authenticate browser repair handoff requests`. Record the result in the tracker; do not start Task 2 until Task 1's functional result has been reported.

## Task 2: Journal capture/recheck boundaries and emit an honest repair request

**Deliverable:** The runner can yield authenticated foreign-owner failures, recover missing structured capture evidence within its remaining allowance, and reject an owner repair whose browser recheck still fails. Ralph integration follows separately.

**Files:** Modify `delivery_slice_journal.py`, `delivery_slice_runner.py`, and the handoff helper; extend `test_delivery_browser_handoff.py` and `test_delivery_slice_recovery.py`.

**Interfaces:** Extend `DeliverySliceRunner.run` with the following optional parameters. Defaults leave existing callers unchanged:

```python
resolve_browser_owner: Callable[[BrowserRepairRequest], str] | None = None
continuation: dict[str, object] | None = None
require_browser_recheck: bool = False
```

The resolver callback is supplied by Ralph and delegates to Task 1's authenticated selector. It does not write state. Same-task results continue normal repair feedback; different-task results yield the typed request. Ambiguity raises, rather than returning an arbitrary fallback owner.

Use a version 3 journal envelope only for new handoff/continuation operations: all existing version 2 fields plus `continuation`, `browser_checks`, and `require_browser_recheck`. Ordinary existing version 2 journals retain their current validator and bytes. `continuation` contains the kind (`refresh`, `owner_retry`, or `return`), predecessor references, source-task identity, entry candidate/input fingerprints, and carried allowance. Validate those values against the referenced history before dispatch.

`browser_checks` is a bounded ordered list of controller records, separate from provider `records`. Each record contains exactly `checkpoint_id`, `purpose`, `after_dispatch_id`, `candidate_fingerprint`, `input_fingerprint`, `repair_attempt`, `request_ordinal`, and `receipt`. Purposes are `refresh`, `owner_recheck`, or `return_capture`; a null receipt is a durable intent. Completed entries refer to ordinary bound browser receipts. IDs are deterministic from operation, purpose, anchor dispatch, and ordinal. Neither controller records nor continuation links fabricate a role result.

- [ ] **1. Write runner regression cases before changing the validator.** Use the real runner and scripted external responses. After a failed capture, the foreign-owner case must yield without another implementer or review dispatch:

```python
assert result.status == "browser_repair_required"
assert not result.succeeded and not result.task_ids
assert result.browser_repair_request is not None
assert [a["step"] for a, _, _ in executor.calls] == ["implementer"]
assert tasks_path.read_bytes() == tasks_before
```

For same-owner failure, assert that feedback goes to the same implementer and no handoff request is returned. For unidentified/mixed failures, assert no foreign dispatch is authorized.

- [ ] **2. Write checkpoint tests.** Persist a capture intent, interrupt, reconstruct, and show that the spent ordinal remains spent. Persist a receipt and interrupt before advancement: reconstruction must reuse it, with zero captures. A failed owner recheck after three passing reviews must permit exactly the next review-guided repair round, not terminal acceptance. A passing recheck permits completion; exhausted rounds do not.
- [ ] **3. Run RED.** Run the new handoff and selected recovery tests; verify the current runner either lacks the typed yield or incorrectly treats the post-review boundary as terminal.
- [ ] **4. Extend validation in place.** Factor the existing role-chain validation only enough to accept a starting allowance and controller-recheck boundaries. Share its allowance interpretation with `continuation_allowance` rather than introducing a second counter algorithm. Do not replace the existing runner with an event engine. Require monotonically consumed ordinals and rounds, immutable predecessor references, matching candidate/input bindings, unique checkpoint IDs, and a resolved recheck before accepting an operation that requires one. Validate version 2 with its unchanged contract. Extend Task 1's resolver to accept a completed controller capture checkpoint anchored to an authenticated predecessor dispatch; do not pretend the checkpoint was a new agent result.
- [ ] **5. Implement the browser-failure branch.** After persisting and authenticating a capture, construct the request and call Ralph's resolver. The essential branch is:

```python
if not observation.verification_passed and resolve_browser_owner is not None:
    owner = resolve_browser_owner(request)
    if owner != task_id:
        return outcome_browser_repair(request)
```

Define `outcome_browser_repair(request: BrowserRepairRequest) -> BuildResult` as a local runner outcome builder preserving actual duration/usage but setting `status="browser_repair_required"`, `exit_code=1`, no accepted task IDs, and the typed request. It is not the existing successful `outcome` branch.

- [ ] **6. Implement controller checkpoints.** Write intent before invoking `browser_baseline_capture`, persist its bound receipt before continuation, then read/validate that receipt for decisions. For a failed owner recheck, retain failure feedback and consume the next repair round after recording the rejection. For a return continuation, capture under the returned task before its implementer dispatch. Never offer owner-recheck images as returned-task evidence.
- [ ] **7. Implement old-evidence refresh without rewriting it.** On an eligible completed, unchanged request with a version 2 receipt, prepare a linked `refresh` continuation that imports consumed allowances, not provider records. This includes the current completed duplicate-request boundary. Record a new capture intent within its remaining allowance. Reject unknown dispatches, changed inputs/candidate, missing predecessor bytes, or an exhausted allowance. A completed refresh receipt is reused on every subsequent resume.
- [ ] **8. Run GREEN and mutation checks.** Run `test_delivery_browser_handoff.py`, `test_delivery_slice_runner.py`, `test_delivery_slice_recovery.py`, and `test_browser_capture_failures.py`. Demonstrate that resetting a carried capture count or treating passing reviews as sufficient for an owner operation makes the corresponding regression fail; use in-memory/test-local mutation, not edits to the demo.
- [ ] **9. Commit.** `fix(delivery): checkpoint bounded browser repair transitions`. Record counts and the explicit fact that native Ralph handoff is not wired yet.

## Task 3: Execute owner repair and source-task return through Ralph

**Deliverable:** A complete controlled T-011 → T-012 → T-011 path, with explicit active-operation selection and exactly-once accounting.

**Files:** Modify `ralph.py` and `delivery_browser_handoff.py`; create `test_delivery_browser_handoff_execution.py`.

**Interfaces:** Add these narrowly scoped Ralph methods. They use the existing state store and runner; no provider dispatch occurs inside operation selection:

- `_select_browser_repair_operation(self, request: BrowserRepairRequest, *, worktree: Path, spec_dir: Path, scope: set[str] | None) -> dict[str, object]`
- `_select_browser_return_operation(self, *, worktree: Path, spec_dir: Path) -> dict[str, object]`

Both return the selected operation snapshot after persistence. Selection prepares/validates the new journal first, then writes `delivery_slice_operation` before any LLM call. They do not call themselves recursively. The owner operation contains `browser_handoff` metadata with exactly `source_operation` (the preserved original snapshot), `source_journal`, `trigger`, and `phase` (`owner` or `return`). The return phase additionally binds the accepted owner journal and passing recheck. Persisted source snapshots are historical context, never additional active work.

- [ ] **1. Build the functional fixture from existing components.** Reuse `_project` from `test_delivery_repair_ownership` for two DONE tasks, real Git/spec files, Ralph and StateStore; replace only its scripted executor and the external `VisualRalphController.capture_baselines` boundary. Do not mock `select_delivery_repair_task`, journal IO, operation selection, or task-progress application. Drive source repair with `controller._exec_feedback` using the real `E2E-START-002` failure identity.
- [ ] **2. Write the failing end-to-end controller assertions.** Script T-011 requesting capture; the capture returns `CT-NET-001`. Script normal T-012 implementation/reviews and a passing browser recheck; then T-011's separate fresh capture, implementer, and independent reviews. Assert the real dispatch sequence:

```python
assert [(a["task_id"], a["step"]) for a, _, _ in executor.calls] == [
    ("T-011", "implementer"),
    ("T-012", "implementer"), ("T-012", "spec_guard"),
    ("T-012", "code_reviewer"), ("T-012", "test_guardian"),
    ("T-011", "implementer"), ("T-011", "spec_guard"),
    ("T-011", "code_reviewer"), ("T-011", "test_guardian"),
]
assert result["task_ids"] == ["T-011"]
assert store.read()["tokens_used"] == 63  # nine seven-token responses
assert source_journal_path.read_bytes() == source_journal_before_handoff
assert owner_recheck_ref != source_return_capture_ref
```

Record the first source journal bytes immediately after its capture receipt is saved. Check distinct receipt task IDs, unchanged outer/inner counters, and that the post-handoff progress result is not T-012 masquerading as T-011.

- [ ] **3. Add failed-recheck and third-owner cases.** Make T-012 reviews pass but its browser recheck fail with `CT-NET-001`; assert another T-012 round and fresh reviews within its remaining limit. Make that recheck identify a third task: assert a descriptive ownership blocker, no nested operation, and no T-011 acceptance. Alter spec/scope/role inputs during the pause and assert refusal before the next dispatch.
- [ ] **4. Run RED.** `.venv/bin/python -m pytest tests/unit/test_delivery_browser_handoff_execution.py -q`; current Ralph must fail the handoff sequence rather than the fixture setup.
- [ ] **5. Wire one iterative control path inside `_exec_controlled_slice`.** Handle the typed request before ordinary blocked/done adaptation. Authenticate and resolve again at state selection, save the paused source snapshot, select the deterministic owner operation, and run it through the normal runner with `require_browser_recheck=True`. Keep its acceptance private until that recheck passes. Select the deterministic source continuation, require its task-bound capture, and return only its eventual result to the existing progress/verification caller.

The governing loop is operation-based, not recursive:

```python
# Each iteration reloads the one persisted active operation.
# _exec_controlled_slice's existing runner invocation remains the dispatcher.
if result.browser_repair_request is not None:
    self._select_browser_repair_operation(
        result.browser_repair_request, worktree=worktree, spec_dir=spec_dir, scope=scope,
    )
    continue
if result.succeeded and operation.get("browser_handoff", {}).get("phase") == "owner":
    self._select_browser_return_operation(worktree=worktree, spec_dir=spec_dir)
    continue
```

Before either branch, durably account the completed runner receipts. On each loop, recompute the effective available token budget from the saved cap, known lineage spending, and run budget. Do not keep a stale pre-handoff budget or expose owner success to `_apply_build_task_progress`. A request inside the owner operation may resolve only to that owner; a third owner is a blocker.

- [ ] **6. Verify crash-safe selection order and accounting.** Use existing prepare-journal → select-operation → dispatch ordering. Resume an already prepared deterministic successor only if its contents exactly match the intended bindings. Charge provider receipt deltas through `accounted_tokens`, including a parent completion not yet charged before process loss. The returned build result's token delta covers all newly charged handoff operations once.
- [ ] **7. Run GREEN.** Run the new execution tests plus `test_delivery_controller_integration.py`, `test_delivery_repair_ownership.py`, and the handoff/runner/recovery tests. Report any existing unrelated fixture failures individually. Confirm no new CLI rule, role-prose instruction, or direct provider bypass was added.
- [ ] **8. Commit.** `fix(delivery): repair browser failure owner before returning to source task`.

## Task 4: Prove interruption safety and observe the native workspace path

**Deliverable:** Verified interruption/replay behavior, an independent review, and an honest operational result from the existing workspace. No claim of full convergence unless the live run actually converges.

**Files:** Extend `test_delivery_browser_handoff_execution.py` and `test_delivery_slice_recovery.py`; update this plan and `docs/simplification-control.md` with results.

- [ ] **1. Add parameterized crash injection at actual persistence boundaries.** Use `ProcessLost(BaseException)` and wrap `DeliverySliceJournal.save` or `StateStore.write`. The wrapper must perform the real write before raising for after-write cases; reconstruct Ralph using `_reconstruct` from `test_delivery_controller_integration`. Cover:

```python
@pytest.mark.parametrize("boundary", [
    "before_owner_selection", "after_owner_selection",
    "after_owner_provider_receipt", "after_owner_accounting",
    "after_recheck_intent", "after_recheck_receipt",
    "before_return_selection", "after_return_selection",
    "after_return_capture_receipt", "after_source_acceptance",
])
```

For each case compare final task/step order, tokens, accepted task IDs, and original evidence bytes with the uninterrupted fixture. No completed provider dispatch or persisted capture receipt may be repeated. An unresolved capture intent consumes its ordinal and may retry only with another available ordinal.

- [ ] **2. Add boundary-limit regressions.** Exhaust the token allowance before owner dispatch, after owner review, and before source return. Replay with the same cap and assert no extra provider call/charge. Test a provider overshoot, unknown usage, final capture ordinal, and final repair round. A later explicit budget increase must use existing admission behavior; the handoff itself never increases it.
- [ ] **3. Test the stopped-run shape.** Construct two completed same-candidate browser requests, the first bound to a version 2 receipt and the second with no capture receipt, exactly as observed. Resume through real Ralph. Assert one allowed structured refresh, then owner selection; original receipt and journal bytes remain unchanged. Alter candidate/input or exhaust the allowance and assert no refresh or provider work.
- [ ] **4. Run the focused gate.**

```bash
.venv/bin/python -m pytest tests/unit/test_delivery_browser_handoff.py tests/unit/test_delivery_browser_handoff_execution.py tests/unit/test_delivery_slice_runner.py tests/unit/test_delivery_slice_recovery.py tests/unit/test_browser_capture_failures.py tests/unit/test_browser_baseline_evidence.py tests/unit/test_visual_ralph.py tests/unit/test_delivery_repair_ownership.py tests/unit/test_delivery_controller_integration.py -q
```

- [ ] **5. Run the repository gate once.** `.venv/bin/python -m pytest -x -q`. Report the known `tests/e2e/test_ralph_convergence.py::TestRalphConvergence::test_converges_within_3_outer_iterations` fixture failure if it remains. Do not edit unrelated tests or claim a green repository gate.
- [ ] **6. Obtain independent read-only range review.** Review from `20e88b0d` through the implementation head using the approved spec and this plan. Resolve substantive findings with failing tests and rerun the affected functional checks before proceeding. Do not spawn implementation agents; native execution remains selected.
- [ ] **7. Confirm the native runtime and live state before resuming.** Inspect the installed module path and version, the exact pending operation/candidate, capture and token allowances, and whether any Delivery process is already active. Reinstall only if the installed CLI is not using the tested source. Do not launch a duplicate run or overwrite workspace bundles unnecessarily.
- [ ] **8. Resume the existing run without extra flags or budget changes.** From `/Users/michalbachorik/work/echelon_r/echelon-acceptance-hygiene.h0fKgr/workspace`, use:

```bash
/Users/michalbachorik/.echelon/venv/bin/echelon delivery continue 001-simple-three-js-demo
```

Do not use `--reconcile-unknown-dispatch` for the two completed browser requests. If native admission requires a change outside the tested contract or limits leave no admissible action, stop and report the exact blocker; do not manually reset state or raise limits.

- [ ] **9. Observe durable results, not only terminal prose.** Check the refreshed receipt, selected T-012 operation, its own review/recheck receipts, separate T-011 return capture, fresh T-011 reviews, tokens, and final verification state. Stop at the first reproducible harness failure. Application repairs must come only from Echelon's assigned implementer. Record unsuccessful outcomes as such.
- [ ] **10. Commit the verification checkpoint.** Commit tests/tracking as `test(delivery): verify browser repair handoff recovery`. Record exact commit, test commands/counts, live-run status, and remaining STAB-1 work. Do not push without a user request.

## Plan review and execution state

- [x] Written design approved by user instruction to proceed.
- [x] Plan maps each design boundary to an implementation/test task.
- [x] Native execution preserved from the user's earlier choice.
- [x] User reviewed this implementation plan.
- [x] Task 1 complete and its functional result reported: 173 focused/adjacent tests passed; live routing unchanged.
- [x] Task 2 complete: 204 focused tests passed, including 26 checkpoint/continuation cases; mutation checks failed as intended. Native Ralph routing not wired yet.
- [x] Task 3 complete: 241 focused tests passed; four pre-existing stale round-count assertions reproduced with prior Ralph and reported separately. Native run not resumed.
- [ ] Task 4 complete; actual workspace outcome recorded.

### Task 4 execution checkpoint — review fixes and native admission

Implementation commits through `42c42cb0` received one independent range review.
All four Important findings were reproduced with regression tests and fixed:

- Provider failure/unknown-outcome recovery after requested, return, and prior-round
  owner captures: six cases. Retain the original v3 capture identity through the
  existing sealed supersession chain; authenticate the retained checkpoint prefix
  and origin rather than relabeling receipts. Fresh operations still start with
  `run_id=operation_id`; v2 behavior is unchanged.
- PENDING source completion interrupted before/after progress state persistence:
  two cases. Authenticate immutable entry inputs separately from the existing
  exact accepted-progress transition. Changed spec/scope/role checks still pass.
- Redirected requested/owner/return capture ancestry: three cases. Constrain
  checkpoint receipt paths at journal IO before reading evidence.
- Explicit v2 budget extension: positive/negative cases. Preserve the admission
  field for the existing runner; old evidence and consumed allowances stay intact.

Each finding followed RED→GREEN. Expanded functional gate (the Task 4 gate plus
checkpoint, failed-review recovery, and unknown-dispatch recovery tests):
**393 passed, 4 deselected in 184.31s**. The four exclusions are the previously
reproduced stale round-count fixtures. Repository fail-fast:
**96 passed, 1 failed in 38.34s**, at the known
`TestRalphConvergence::test_converges_within_3_outer_iterations` fixture. Review
raised no Critical/Minor findings and declined no judgments. No second reviewer.

Native runtime paths both point into this worktree. With no active Delivery
process, the exact Task 4.8 command was attempted and exited 1: CLI admission
rejects `build_blocked` / `delivery_browser_evidence_request_repeated` before
Ralph. No provider ran. The target state file's SHA-256 was unchanged:
`14a531f00d2a9a921149d993bb2a12f4a310eaaae8cbc0e9b6f56c89e2537ff5`.
Usage remains 34,990,865/50M; operation remains
`fb2d0a3533714e44a501940f3841fba5`. Bundles reported zero changed files.

Per Task 4.8, stop/report this admission blocker before expanding scope. Do not
reset the run, reopen the spec, or reconcile these completed requests as unknown
dispatches. The next narrowly scoped change is native admission for authenticated
pending browser recovery, followed by the same command and observation. Task 4
remains incomplete; this is not a convergence or workspace-acceptance receipt.

### Approved admission follow-up

After the boundary was reported, the user approved harness-owned eligibility,
with CLI forwarding/display only. The bounded correction moves the existing
provider-failure, cancelled-slice and prior-review-cap predicates into
`harness.delivery_controller.pending_slice_resume_supported`, alongside the
pending browser-request classification. CLI status and continuation consult the
same policy. Classification is not recovery authorization: Ralph's locked runner
still validates current evidence, candidate, ownership and consumed allowances.

RED: actual CLI entry rejected the eligible retained browser operation both with
and without a configured root verifier. GREEN: 100 CLI/recovery tests passed in
72.67s, including negative phase/operation/unknown-dispatch cases; 121 functional
handoff/controller/lock tests passed in 82.06s. Repository fail-fast: 96 passed,
one known convergence-fixture failure in 41.08s. No reset, limit change, demo edit
or provider recovery flag was introduced. Native retry follows this checkpoint.

Native retry on `3b839ffb` passed admission and selected refresh
`8744822883aef06eaba8761969deb5591c83211f612b9fdd0c84a819389f3043`.
The persisted capture intent consumed ordinal 3, retaining 1,512,309 carried
tokens and the original 14,021,444 operation cap. The new v3 receipt
`c22a61d1c17a45ebbe7ddcc1b0c54ce8` reported `CT-NET-001` with zero unidentified
failures, and the harness selected T-012 owner operation
`bcc65da013e62bc359de68e7c3ac2cc7c5d47ccacd4f8d349f98377effaf0189`.
The assigned implementer is executing. Owner review/recheck, source return and
final acceptance remain unverified; observation continues. No manual demo edits.
