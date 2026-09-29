# Delivery Review Evidence Recheck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a delivery reviewer from sending an uninspected candidate-test absence claim into product repair, while preserving genuine review failures and crash-safe recovery.

**Architecture:** Extend the existing four-role controlled slice, not its ownership model. A reviewer result carries its candidate-test read set; the controller atomically journals whether that read set is complete and permits one same-role, read-only context recheck. Only the resolved verdict enters the current aggregate repair routing.

**Tech Stack:** Python 3, existing delivery slice journal, Prosaic role prompts, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-delivery-review-evidence-recheck-design.md`

## Global Constraints

- Change Echelon only. Do not manually edit generated demo code, task progress, or review gates.
- Reuse `DeliverySliceJournal`'s intent-before-provider and receipt-before-advance pattern. Never rerun an unknown-completion dispatch.
- At most one read-only same-role evidence recheck for an incomplete negative SPEC GUARD or TEST GUARDIAN result; it does not consume an implementation repair round.
- Require complete candidate-test accounting on the recheck even if its verdict becomes PASS. A second incomplete result blocks explicitly.
- Preserve prior receipt validation and the current run's exact candidate/spec/role bindings; do not migrate or erase journals.
- The normal three independent passing reviews and subsequent authoritative verification remain required.

## Review Focus

- Tests outside the task's Files list amid hundreds of unrelated tests: the task-relevant set finds them without requiring the whole suite, and an omission causes recheck rather than product repair (Task 1/3 tests).
- A genuine negative review after complete evidence: it reaches the existing aggregate implementer repair (Task 3 test).
- A second incomplete read set, including a claimed PASS: it blocks without acceptance or a third review dispatch (Task 2/3 tests).
- Crash after the first review result or after recheck intent: replay uses receipts and never duplicates a provider call (Task 2/3 tests).
- Candidate mutation or exhausted token budget between reviews: no recheck runs against stale or unaccounted inputs (Task 3 tests).

---

### Task 1: Candidate test evidence contract

**Files:**
- Modify: `src/harness/delivery_slice.py` — optional, validated `reviewed_test_paths` in SPEC GUARD and TEST GUARDIAN results.
- Modify: `src/harness/delivery_slice_runner.py` — enumerate runnable tests and derive a task-relevant audit set without treating task Files as exhaustive.
- Test: `tests/unit/test_delivery_slice.py`
- Test: `tests/unit/test_delivery_slice_runner.py`

**Interfaces:**
- Consumes: `DeliveryAssignment`, `validate_delivery_result`, `_candidate_file_inventory`.
- Produces: reviewer `result["reviewed_test_paths"]: list[str]` when supplied; `_candidate_file_inventory(worktree)["test_paths"]: list[str]` of existing runnable candidate tests; `_candidate_test_audit_set(worktree, tasks_markdown, task_id, path_projection, inventory): list[str]` of required task-relevant tests.

- [ ] **Step 1: Write failing contract tests.** Verify a negative reviewer result may carry `reviewed_test_paths`, duplicate/absolute/escaping paths and the field on other roles are rejected, and legacy results still validate. Verify `tests/integration/main-entry.test.ts` is inventoried while `tests/fixtures/browser.ts` is not. With a task declaring `tests/integration/bootstrap.test.ts` and `src/main.ts`, assert the audit set contains sibling `main-entry.test.ts`, a test importing `src/main.js`, and a changed test, but not hundreds of unrelated unit tests; an over-limit audit set must return an explicit error, not a truncated list.

```python
payload = {**assignment.identity(), "verdict": "FAIL", "summary": "Missing coverage",
           "findings": ["tests/integration/bootstrap.test.ts:1 misses entry wiring"],
           "reviewed_test_paths": ["tests/integration/bootstrap.test.ts"]}
assert validate_delivery_result(json.dumps(payload), assignment)["reviewed_test_paths"] == [
    "tests/integration/bootstrap.test.ts"
]
```

- [ ] **Step 2: Run the exact new tests RED.** Use `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_slice.py tests/unit/test_delivery_slice_runner.py -k 'reviewed_test_paths or candidate_inventory'`; confirm failure is the missing contract/incorrect inventory, not fixture setup.
- [ ] **Step 3: Implement the narrow schema and audit-set builder.** Accept the optional field only for the two test-review roles, validate canonical repository-relative strings and uniqueness, and retain old envelopes. Derive task paths through `task_files_section_for` and the existing candidate path projection; include declared runnable tests, runnable siblings, changed tests, and tests referencing selected source paths or extensionless stems. Keep the full path inventory for navigation, but never use its 200-path display truncation as the audit authority. Fail explicitly if the audit set exceeds its bound.

```python
if assignment.step in {"spec_guard", "test_guardian"} and "reviewed_test_paths" in payload:
    paths = payload["reviewed_test_paths"]
    if not isinstance(paths, list) or any(not _safe_relative_test_path(p) for p in paths):
        raise DeliverySliceError("invalid reviewed test paths")
```

- [ ] **Step 4: Run both files GREEN and commit.** Use the same focused pytest command without `-k`; inspect `git diff --check`, then commit only Task 1 files.

### Task 2: Durable same-role recheck receipts

**Files:**
- Modify: `src/harness/delivery_slice_journal.py` — optional `review_evidence` receipt, validated repeat transition and bound.
- Test: `tests/unit/test_delivery_slice_recovery.py`
- Test: `tests/unit/test_delivery_slice_runner.py`

**Interfaces:**
- Consumes: a complete provider `result` plus a controller-owned `review_evidence` record shaped as `{"audit_test_paths": list[str], "incomplete": bool}`.
- Produces: at most one same-step continuation for an incomplete SPEC GUARD or TEST GUARDIAN receipt on an unchanged candidate/repair round. A second incomplete receipt is terminal.

- [ ] **Step 1: Write failing journal tests.** Construct real `DeliverySliceJournal` data and bound result JSON for a SPEC GUARD FAIL that omits an off-task test. Assert a second SPEC GUARD intent may follow without incrementing `repair_attempt`, but a third cannot. Assert forged `incomplete=False`, unknown test paths, or a reviewer mutation cannot authorize a repeat. Keep runner-level crash/replay behavior for Task 3, whose runner changes create these receipts.

```python
first = journal["records"][1]
assert first["assignment"]["step"] == "spec_guard"
assert first["review_evidence"] == {
    "audit_test_paths": ["tests/integration/main-entry.test.ts"], "incomplete": True
}
assert journal["records"][2]["assignment"]["step"] == "spec_guard"
assert journal["records"][2]["repair_attempt"] == first["repair_attempt"]
```

- [ ] **Step 2: Run the new recovery cases RED** with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_slice_recovery.py tests/unit/test_delivery_slice_runner.py -k 'review_evidence_recheck'`.
- [ ] **Step 3: Extend only the existing journal state machine.** Validate `review_evidence` atomically with its raw bound result, calculate incompleteness from recorded `audit_test_paths` and `result.get("reviewed_test_paths", [])`, retain legacy receipts without the new field, allow one same-step repeat, and set the maximum receipt count to `MAX_GATE_ROUNDS * 6 + 2` for two possible reviewer rechecks per round plus existing browser evidence requests.

```python
if review_evidence is not None and review_evidence["incomplete"]:
    if rechecks_for_step == 1:
        terminal = True
    else:
        rechecks_for_step = 1  # Keep step_index unchanged for the next intent.
else:
    step_index += 1
    rechecks_for_step = 0
```

- [ ] **Step 4: Run recovery and runner tests GREEN, inspect `git diff --check`, and commit only Task 2 files.** Do not increase the implementation repair cap.

### Task 3: Reviewer-context routing and functional probe

**Files:**
- Modify: `src/harness/delivery_slice_runner.py` — compute/save evidence decision with result; one targeted same-role redispatch; restore original feedback for subsequent roles.
- Modify: `prosaic/subagents/echelon.delivery-spec-guard.md`
- Modify: `prosaic/subagents/echelon.delivery-test-guardian.md`
- Test: `tests/unit/test_delivery_slice_runner.py`
- Test: `tests/unit/test_delivery_slice_recovery.py`

**Interfaces:**
- Consumes: Task 1 candidate-test audit set and optional result field; Task 2 `review_evidence` receipt transition.
- Produces: `delivery_review_context_unresolved:<step>` only after a second incomplete evidence result; otherwise the existing PASS/FAIL routing and aggregate findings.

- [ ] **Step 1: Write failing runner tests.** Use `ScriptedExecutor` with a candidate `main-entry.test.ts` outside the task Files list: first SPEC GUARD FAIL names only `bootstrap.test.ts`; recheck sees the omitted source and returns PASS with the complete path list. Assert dispatch order `implementer, spec_guard, spec_guard, code_reviewer, test_guardian`, one repair round, and no acceptance before all three passing reviews. Repeat with a complete recheck FAIL and prove the normal implementer repair follows; repeat with an incomplete recheck PASS and prove explicit block.

```python
assert _steps(executor)[:5] == [
    "implementer", "spec_guard", "spec_guard", "code_reviewer", "test_guardian"
]
assert result.reason == "delivery_gates_passed"
```

- [ ] **Step 2: Run those tests RED** with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_slice_runner.py -k 'review_context_recheck'`.
- [ ] **Step 3: Implement runner dispatch/replay.** Build the candidate test audit set immediately before each review; save its paths and evidence-completeness decision in the same journal write as the result. On incompleteness, construct a read-only packet of omitted test sources up to 128 KiB, or exact paths with mandatory read instructions beyond that size. Verify paths remain inside the candidate and its fingerprint is unchanged, then redispatch the same role once. Count tokens for both calls. Never pass context-recheck feedback to another role or the implementer.

```python
if record.get("review_evidence", {}).get("incomplete"):
    if review_rechecks:
        raise DeliverySliceError(f"delivery_review_context_unresolved:{step}")
    review_rechecks += 1
    repair_context = _review_recheck_context(worktree, record, result)
    continue  # Same role, new durable dispatch intent.
```

- [ ] **Step 4: Verify recovery, boundaries, and full project tests.** Run the changed runner/recovery/contract tests, then `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest` and report any unrelated failures by name. Run `git diff --check` and commit only Task 3 files.
- [ ] **Step 5: Functional probe without product edits.** Reinstall Python-only Echelon from this worktree, run a small disposable scripted review that reproduces the earlier false-absence finding, and inspect its journal and dispatch order. Then check whether the blocked rugby-demo run has a supported new-operation path. Do not rewrite its capped journal, change demo files manually, or claim Delivery passed unless the actual review and authoritative verification complete.

## Completion handoff

Compare the implementation against the spec, inspect the final diff for journal replay and gate-bypass bugs, and report exact test counts plus the disposable probe result. Keep the rugby-demo's genuine listener and RAF findings visible for normal product repair.
