# Delivery Controller Phase 2 Implementation Plan

> Execute inline with test-first checkpoints. Use executing-plans; request an
> independent read-only review before the phase handoff.

**Goal:** Trial Python-owned implementation and sequential review gates, with
strict blocking after two unsuccessful repair attempts in every autonomy mode.

**Architecture:** A bounded slice selector and result validator feed a dedicated
provider-backed runner. Ralph uses it for build and feedback only under an
explicit feature flag; legacy status files cannot satisfy the new gates.

**Tech Stack:** Python, Prosaic profiles, existing provider facade, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-delivery-controller-ownership-design.md`

## Constraints

- Preserve canonical task identities and target containment.
- No live delivery, provider configuration change, installation, merge or push.
- No automatic DEGRADED approval, gate skipping, or fallback on the trial path.
- Keep mode/autonomy logic unchanged; strict gate acceptance applies to all modes.
- Diagnostic output is not a resumable authority; phase 3 supplies durable reuse.
- Keep the feature off by default until recovery and finalization cutover.

## Task 1: bounded scope and result contracts

Files: `src/harness/delivery_slice.py`, `tests/unit/test_delivery_slice.py`.

- [x] Write failing tests for canonical dependency order, explicit target scope,
  unknown IDs/dependencies, cycles, empty/all-completed scope, and repair of an
  already completed task. Assert the selected task, not parser implementation.
- [x] Implement `select_delivery_task(spec_dir, allowed_task_ids=None,
  repair_task_id=None) -> str` using the canonical parser/progress summary.
  Unknown or empty explicit scopes, missing dependencies, cycles, and malformed
  rows raise `DeliverySliceError`. Only DONE/DONE_WITH_CONCERNS satisfy a dependency.
- [x] Write failing tests for strict JSON results. Require exactly
  `schema_version`, `dispatch_id`, `step`, `task_id`, `candidate_fingerprint`,
  `input_fingerprint`, `verdict`, `summary`, `findings`. Reject stale identity,
  unknown/DEGRADED/SKIP verdicts, nonzero exits, contradictory findings, and
  oversized/malformed output. No legacy marker or output-text recovery.
- [x] Implement immutable `DeliveryAssignment` and `validate_delivery_result`
  with per-step allowlists and the dispatch-bound identity.

Concrete success payload for a SPEC GUARD response:

```json
{"schema_version":1,"dispatch_id":"attempt-1","step":"spec_guard",
 "task_id":"T-001","candidate_fingerprint":"candidate-sha",
 "input_fingerprint":"inputs-sha","verdict":"PASS",
 "summary":"All assigned criteria have source evidence.","findings":[]}
```

## Task 2: executing the bounded gate chain

Files: `src/harness/delivery_slice_runner.py`,
`prosaic/subagents/echelon.delivery-{implementer,spec-guard,code-reviewer,test-guardian}.md`,
`tests/unit/test_delivery_slice_runner.py`.

- [x] Use a scripted external executor and real files/loader. Demonstrate exact
  order `implementer, spec_guard, code_reviewer, test_guardian`; no task accepted
  until the final passing response. Change candidate content after implementation
  and prove reviews receive the new fingerprint.
- [x] Implement `DeliverySliceRunner(executor, project_dir).run(worktree,
  spec_dir, evidence_root, allowed_task_ids=None, repair_task_id=None,
  feedback='', stop_requested=None) -> BuildResult`.
- [x] Preflight provider read-only capability and all role resources before work.
  Load the four installed Prosaic roles with neutral framing and their model
  metadata. Embed canonical spec/task context, not the old MANAGER command body.
- [x] Return results on stdout; only Python writes diagnostic JSON. Review
  metadata has exclusive write scope and no writable paths. Implementer may
  mutate candidate source/tests only. Detect spec changes after any dispatch,
  and candidate changes during any review. Bind relevant spec inputs and
  candidate contents to each assignment; refuse symlinked spec inputs.
- [x] On a negative review route findings to implementation, discard previous
  reviews, and restart SPEC GUARD. Permit exactly two repair implementations
  total. Invalid output, mutation, explicit BLOCKED, cancellation, provider
  failure, or exhausted repairs stop without accepted task IDs.
- [x] Test those failure paths, unknown providers, missing roles, stdout failure,
  and correct usage aggregation. Preserve diagnostic attempts, not reusable receipts.

## Task 3: Ralph trial boundary

Files: `src/harness/ralph.py`, `src/harness/coordinator.py`,
`src/harness/config.py`, `tests/unit/test_delivery_controller_integration.py`.

- [x] Add tests showing `llm.features.delivery_gate_controller: true` routes
  real Ralph build and feedback through all four external calls; disabling it
  preserves the old path. Reject non-boolean flag values instead of silently
  falling back. No change to provider selection.
- [x] For the controlled path, pass argument/context data without loading the
  legacy build body. Retain `echelon build` identity validation. Ralph creates
  containment policy through its existing context preparation, then supplies
  the actual worktree/spec roots, persisted target IDs, cancellation signal,
  and only the repair context to the new runner.
- [x] Persist the last accepted slice task for same-task feedback. Empty scope
  must not broaden into an unrestricted selection. Missing repair identity blocks.
- [x] Translate the runner's BuildResult at the existing Ralph result boundary.
  Only accepted task IDs reach progress marking; gate failures must stay blocked
  even if sandbox verification would otherwise pass, including in banzai.
- [x] Run phase-1, new phase-2, Ralph inner/outer, coordinator/reentry,
  continuation, mode, provider, config, and polyrepo tests.

## Task 4: review and handoff

- [x] Review actual provider dispatch behavior independently; fix important findings.
- [x] Document feature activation, strict retry policy, current provider support,
  and the phase-3/4 limitations. Do not call this a production cutover.
- [x] Run final regression and whitespace checks; record exact results.
- [x] Commit a separate phase-2 checkpoint on the isolated branch.

## Trial activation and limits

After explicitly choosing to install this branch and refresh the workspace's
Prosaic bundle, the opt-in is:

```yaml
harness:
  llm:
    features:
      delivery_gate_controller: true
```

Do not change the selected provider to activate this feature implicitly. The
current enforced review capability is Codex with its supported host boundary.
Other providers, missing role profiles, invalid specs, and empty targeted scope
block before implementation. The flag defaults to false and requires an actual
YAML boolean. No runtime configuration was changed during development.

The first implementation plus at most two repair implementations are allowed.
Any repair invalidates all previous reviews. DEGRADED/WARN/SKIP cannot replace a
passing verdict. This acceptance policy is the same in banzai, semi, and guided;
ordinary phase pauses and escalation policy are unchanged.

This is not a production-default cutover. Diagnostic assignments/results are
retained outside the candidate worktree but are never reused as approvals.
Restart-safe retry/receipt authority is phase 3. Documentation-only work with
no pending task blocks explicitly until phase 4; it never falls back to the old
MANAGER invocation. Existing non-opt-in delivery remains unchanged.

## Checkpoint verification (2026-09-11)

- Final combined regression: **1,008 passed in 86.69 seconds**. This covers the
  new selector, runner and integration tests; phase-1 prompt setup; Ralph,
  coordinator/reentry, continuation, modes/banzai, config, Prosaic authoring and
  execution policy, provider/backend permissions, and polyrepo convergence.
- Independent read-only review findings were reproduced with failing tests and
  fixed: authoritative clarification inputs, trailing task-row whitespace,
  protected configuration/profile writes, legacy external-target empty scopes,
  and symlinked candidate configuration escaping into the orchestration root.
  Final narrow review reported no remaining important findings; its runner
  suite passed all 27 cases.
- Installed Prosaic inspection accepted the new read-only role profile. Provider
  integration uses the real facade with a scripted external backend; no live LLM
  delivery was run. These results are not a full-repository test-suite claim.
- The runner also accepts containment policy and remaining token budget. Unknown
  usage stays unknown and blocks further execution under a finite budget.
- Whitespace checks passed. The checkpoint is isolated on
  `fix/delivery-controller-contract`; no installation, runtime configuration,
  main-checkout change, merge, or push was performed.

### Reproduce the focused subset

With the project test environment active, from this branch:

```bash
python -m pytest -q tests/unit/test_delivery_slice.py \
  tests/unit/test_delivery_slice_runner.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_delivery_prompt.py tests/unit/test_mode_controller.py \
  tests/unit/test_prosaic_execution_policy.py --tb=short
```
