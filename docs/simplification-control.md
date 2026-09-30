# Echelon Simplification Control

**Rule:** one `ACTIVE` milestone at a time. Finish or explicitly block it before
starting another.

**Design:**
[`2026-09-21-harness-simplification-control-design.md`](superpowers/specs/2026-09-21-harness-simplification-control-design.md)

**Current milestone:** STAB-1 — provider finalization / workspace acceptance

### Current branch follow-up: browser repair handoff (2026-09-30)

Within STAB-1, structured browser-failure retention is complete on
`fix/browser-evidence-handoff` at `20e88b0d`: 209 focused tests passed, independent
review approved, and an isolated Docker capture's `CT-NET-001` failure resolved
to T-012 through the existing ownership selector. This is not a claim of merge,
push, or completed workspace acceptance. The repository-wide fail-fast check
still stops at the known `test_converges_within_3_outer_iterations` fixture's
missing canonical spec directory.

The live continuation using `3b839ffb` stopped at
`delivery_browser_snapshot_recapture_required` (exit 1; 37,952,845 tokens).
T-012 passed independent reviews and its actual browser recheck. T-011 then
received a distinct passing return capture, but installing its exact proposals
changed three baseline PNGs and triggered the runner's candidate-change guard
before fresh reviews. The process ended and observation is paused. These
captures use snapshot-update mode, not final regression/visual acceptance. The
[browser repair handoff design](superpowers/specs/2026-09-30-browser-repair-handoff-design.md)
and four-task
[implementation plan](superpowers/plans/2026-09-30-browser-repair-handoff.md) are approved.
Task 1's read-only handoff contract is implemented: real journal/receipt tests
resolve T-012 without dispatch or evidence writes, preserve same-task repair,
and retain consumed allowances. Focused plus adjacent verification: 173 passed.
Task 2's bounded runner checkpoints are implemented: typed foreign-owner yield,
durable capture intents, failed owner rechecks consuming existing repair rounds,
and linked refresh/return journals preserving source allowances and bytes.
Focused gate: 204 passed, including 26 new checkpoint/continuation cases.
Two in-memory mutations (counter-validation bypass and false passing recheck)
made the intended regressions fail.
Task 3 wires native Ralph owner/return selection and exactly-once accounting:
241 focused tests passed, with four separately reproduced pre-existing
round-count assertions deselected. Those are the three modes of
`test_gate_failure_cannot_be_promoted_by_ralph` and
`test_banzai_outer_loop_does_not_verify_or_accept_rejected_slice`; they expect
four rounds although the existing limit is five. No gate or limit was changed.
At the pre-review checkpoint, Delivery was still stopped. Task 4 interruption
tests, current v2 refresh integration, and independent review have since run.
Task 4 pre-review checkpoint: 328 focused tests passed (four known stale
round-count assertions excluded). Ten crash boundaries preserve dispatches and
accounting. Real Ralph refreshes the stopped v2 two-request shape without
rewriting it. The repository gate still stops after 96 passing tests at the
known convergence fixture.

Post-review checkpoint: four Important findings reproduced and fixed individually:
provider supersession retains authenticated capture identity, accepted source
progress replays across its file/state write boundary, every checkpoint receipt
is confined to the trusted evidence root, and v2 refresh preserves an explicitly
admitted budget extension. The expanded gate passed **393 tests**, with the same
four stale round-count assertions deselected. Repository fail-fast: 96 passed,
then the known convergence-fixture failure; no green full-suite claim.

The installed CLI imports this worktree. Native `echelon delivery continue
001-simple-three-js-demo` exited 1: CLI admission rejects `build_blocked` /
`delivery_browser_evidence_request_repeated` before reaching Ralph. Target
`delivery.json` was byte-identical before/after; usage remains 34,990,865/50M,
active operation `fb2d0a3533714e44a501940f3841fba5`. No demo edits, reset,
unknown-dispatch reconciliation, limit increase, or provider dispatch occurred.
The user subsequently approved a harness-owned admission correction. Existing
provider-failure, cancelled-slice, and prior-review-cap predicates now live in
`harness.delivery_controller`, with supported pending browser recovery. The CLI
consults that policy for routing/status only; locked runner validation still
authorizes evidence, attempts and dispatch. No browser recovery rules were added
to the CLI. Command/recovery tests: 100 passed; handoff/controller/lock tests:
121 passed. Repository fail-fast: 96 passed, then the same known convergence
fixture. The native retry initially reached T-012 without flags or limit changes:
refresh `8744822883ae…` used ordinal 3 and preserved the two prior requests;
owner `bcc65da013e6…` was then active. Capture receipt `c22a61d1c17a45ebbe7ddcc1b0c54ce8`
retains structured `CT-NET-001`, with zero unidentified failures. Task 4 and STAB-1
remain open; no workspace-acceptance claim is made.
No new milestone or S6/S7 work is opened.

Approved bounded follow-up: the existing runner now records the exact projected
post-install candidate fingerprint **before** the return/refresh implementer
dispatch, linked to its authenticated passing capture checkpoint. Only an
unchanged candidate or exact complete proposal installation can proceed to the
existing independent reviews. Source/test edits, altered or partial images,
unlisted images, executable-status changes and symlinks do not gain an exception.
Normal verification and semantic visual acceptance are unchanged requirements.
The installation intent is an optional field on the existing durable dispatch
record, not a new controller or CLI rule. Missing historical intent stays
fail-closed; no live journal, demo code, cap, or review gate was changed.

Verification: the two exact-installation regressions failed first with the live
`delivery_browser_snapshot_recapture_required` reason. The final focused gate
passed **236 tests in 146.67s**, covering controller handoff, new/replaced images,
complete/partial/failed-capture refresh, completed-install crash reconstruction,
malformed/missing intent, recovery, receipt validation and Git-backed fingerprint
projection. Independent review found no blocking issue; both minor points
(executable-status wording and complete-set/refresh coverage) were addressed.
Repository fail-fast remains **96 passed, 1 known failure in 37.00s**:
`tests/e2e/test_ralph_convergence.py::TestRalphConvergence::test_converges_within_3_outer_iterations`.
No green full-suite or live acceptance claim. Detailed command output is retained
in `.superpowers/sdd/2026-09-30-browser-repair-handoff/baseline-installation-{focused,repository}.log`.

The subsequent native run `build-20260930-171628-219713` preserved candidate
`3b51c6550391c8c349a75967431a5cbd611a362d` without reset or reimplementing all
tasks. Ordinary verification passed (127 Vitest tests and 165 Playwright
executions, without snapshot updates). Fulfillment then received no structured
coverage observation because no stack was selected, classified all 54 planned
requirements as deferred coverage, and repair stopped at
`delivery_repair_ownership_required: missing failed test identity for fulfillment-gaps`.
The run and observation heartbeat are stopped; this is not live acceptance.

### Evidence-flow closure, one fix at a time (2026-09-30)

- [x] Stack-prerequisite Task 1: explicit owner stack selection before new Spec
  allocation/dispatch; capability-free `generic` discovery policy. Approved
  policy-only schema relaxation retains strict non-policy/scoped-policy rules.
  Disposable real controller/provider-boundary and Git allocation probes pass;
  admission tests distinguish empty, generic, concrete, invalid and source-local
  empty selections. Commit `284c5d3f`; 129 focused tests passed.
- [x] Stack-prerequisite Task 2: static target-scoped capability readiness;
  generic-only rejection, required observer/runtime/visual checks, owner deferrals,
  shared-case ownership and explicit non-runnable disposition. 183 focused tests
  passed. Additional controller suite has four repair-count expectation failures;
  repository fail-fast still has the known canonical-spec convergence fixture.
  The four repair-count fixtures were corrected to the existing five-chain
  policy in Task 3; production limits are unchanged.
- [x] Stack-prerequisite Task 3: capability-aware publication, service/direct
  Delivery admission, current-owner prompt context, and new-dispatch guards.
  Sealed Spec/Delivery receipts and publication/review effects recover first;
  incompatible current contracts block subsequent work without rewriting saved
  identity or sending capability gaps to product repair. Independent review
  findings reproduced and fixed. Verification: 699 expanded checks, 394 adjacent
  checks, and 295 final current-tree named checks passed (overlapping suites).
  Final repository fail-fast: 96 passed, one known convergence-fixture failure;
  dry-run passed all nine bundle checks. See the
  [stack prerequisite plan](superpowers/plans/2026-09-30-stack-verification-prerequisites.md).
  No install, push, live demo edits or Delivery restart; STAB-1 is still open.
- [x] Detect missing required observer capability before fulfillment, even when
  stack selection is empty. Preserve the explicit `coverage_observer_unavailable`
  blocker through Ralph without dispatching candidate-source repairs or charging
  meaningful attempts. No-map/no-observer verification and intermediate tasks
  without coverage obligations remain supported.
- [x] Mixed-runner observer prerequisite: one stack may explicitly require both
  Vitest and Playwright for a shared test type. Different-stack conflicts remain
  blocked; every required observer is retained, and duplicate physical case
  claims and failed results remain rejected by the existing evidence machinery.
  Resolver/parser/receipt probes and adjacent checks: 177 passed; read-only review
  found no blocking or minor issues. Repository
  fail-fast: 96 passed, the same known convergence-fixture failure. This is not
  an npm observer bundle, actual browser execution, or live Delivery acceptance.
- [x] Add the compatible `browser-threejs-npm` bundle using existing stack,
  isolated-observer, report-adapter, and required browser-runnability contracts.
  Project npm scripts retain their own repetitions and project configuration;
  reporters write JSON separately from console output. No Python production or
  CLI recovery changes. Verification: 247 focused/adjacent tests and all nine
  dry-run checks passed; independent read-only review found no issues. The
  catalog expectation also now includes the previously added `generic` bundle.
  Repository fail-fast remains 96 passed plus the known
  `test_converges_within_3_outer_iterations` canonical-spec fixture failure.
  Actual isolated Docker probes against preserved candidate `3b51c6550391`
  captured passing reports for 165 ordinary Playwright executions (five repeats,
  no snapshot updates) and 127 Vitest tests. Both observer receipts validate;
  candidate fingerprint and live Delivery state are unchanged. Raw reports,
  receipts, and diagnostics are retained under
  `.superpowers/sdd/2026-09-30-stack-verification-prerequisites/npm-observer-probe/`.
  This proves observer execution/capture, not accepted coverage or fulfillment:
  all 37 tagged physical tests still use prefix tags instead of terminal tags.
  Do not edit these manually or weaken parsing; use normal Delivery repair.
  No installation, live stack selection, Delivery restart, or push was performed.
- [ ] Wire compatible structured observers and verify actual execution evidence
  reaches fulfillment for the preserved candidate. Do not blindly select a
  React/pnpm stack for this npm/Three.js candidate or rewrite the planning map.
  Workspace wiring completed through `workspace migrate-to-prosaic` and
  `stack select browser-threejs-npm`; explicit/effective/resolved selection,
  stack preflight, and configured build readiness pass. The installed editable
  CLI already points to this checkout. Runtime refresh created four managed
  files without overwriting existing bundle files; configuration diff is only
  `stacks.selected`. Existing workspace edits were preserved, not committed.
  A read-only production-helper probe of the retained actual reports reproduces
  37 unbound cases due to terminal-tag violations. All cases have unique task
  ownership, spread across eight accepted tasks (T-004 through T-009, T-011,
  T-012). Combined repair admission rejects multiple owners; each diagnostic
  owner partition independently passes admission. No partition was dispatched.
  Focused ownership/admission/runtime/CLI verification: 64 tests passed.
  Probe/log/config-before snapshot are retained in the local
  `.superpowers/sdd/2026-09-30-stack-verification-prerequisites/stack-wiring/`.
  Candidate fingerprint, stopped-run state and published spec/tasks are unchanged;
  Delivery remains paused. The old empty-observer snapshot must not be rewritten
  or reused as evidence for the new stack. Candidate-owned runnability contract
  is also absent; this remains a separate prerequisite before coverage acceptance.
- [x] Approve and implement bounded multi-owner coverage repair selection: one
  uniquely owned task per existing repair operation, full failure evidence
  retained, fresh verification between repairs, pending-operation replay intact.
  Keep ambiguous/unowned cases, target-scope violations, and browser handoff
  single-owner rules fail-closed. Do not introduce a new queue/controller or
  manually repair the demo. Only pure structured coverage-observation failures
  gain canonical-task-order selection; all case owners, target scope, and
  accepted statuses are validated before selecting any owner. Other failure
  formats and strict browser ownership remain unchanged. No Ralph control-flow,
  durable-state schema, CLI or provider-contract changes.
  Four regressions failed before implementation. Verification: 96 focused
  repair/browser/recovery tests and the added real inner-loop sequencing test
  passed; expanded gate finished with 355 passed and 21 existing failures in
  `test_delivery_source_feedback.py`. All 21 also fail with the committed
  pre-change `delivery_slice` module, during initial provider fixture setup.
  Failed test groups are `test_actual_repair_roles_receive_one_contract_and_complete_evidence`
  (18 variants), `test_empty_base_does_not_discard_controlled_failure_evidence`,
  `test_restart_replays_exact_structured_feedback_and_accounts_once`, and
  `test_old_pending_source_repair_blocks_without_rewriting_records`.
  Repository fail-fast: 96 passed plus the known canonical-spec convergence
  fixture failure. Independent read-only review found no issues. Retained-report
  diagnostic now selects T-004 and its four cases from the 37-case report,
  without dispatch. Tests verify full evidence retention, exact pending replay,
  re-verification between distinct owners, and no convergence from reviews
  while coverage still fails. No live candidate edits, restart, caps changes,
  install, push or evidence migration.
- [ ] Correct coverage progress identity before resuming multi-owner repair.
  A read-only hypothetical shrinking-debt probe using the actual coverage map
  demonstrates that the existing first-20-requirement error summary can remain
  unchanged while remaining case debt falls 30 → 28 → 26. The existing repeated
  failure detector would escalate at T-008 despite that progress. Use complete
  structured coverage debt for repeat identity, preserving repeat thresholds,
  caps and true-stagnation escalation. Do not weaken gates or add a queue.
  Probe/log: `stack-wiring/coverage_progress_probe.py` and
  `stack-wiring/coverage-progress-probe.log` under the local evidence directory
  above. This is a simulated diagnostic, not repaired/accepted candidate work;
  implementation remains a separate increment. Candidate runnability contract
  remains another explicitly open prerequisite.
- [ ] Correct semantic visual gate ordering, then test its phase handoff.
- [ ] Address requirement-level fulfillment repair routing separately, with
  evidence-bound ownership and no fallback to the last executed task.
- [ ] Continue native Delivery on the preserved candidate, then complete fresh
  workspace end-to-end acceptance. Do not mark Task 4/STAB-1 complete yet.

First-fix verification: four regressions failed before implementation; the
focused gate passed **221 tests in 14.66s**, including capability blocking,
outer/inner loop handling, configured observer evidence, source/receipt binding,
and coverage classification. A read-only production-gate probe against the live
candidate reported missing `contract`, `e2e`, `integration`, and `unit` observers;
it created no evidence and left run state, coverage plan, and fulfillment report
unchanged. Repository fail-fast: **96 passed, 1 known failure in 41.90s** at
`tests/e2e/test_ralph_convergence.py::TestRalphConvergence::test_converges_within_3_outer_iterations`
(fixture lacks a canonical spec directory). No demo edits, restart, stack
selection, review weakening, or green full-suite claim.
Independent read-only review found no blocking or minor defects in this bounded
change. Observer configuration, live recovery, visual ordering, general repair
routing, and the known fixture failure remain outside this first fix.

## Status

| ID | Status | Outcome | Current evidence | Exit check |
| --- | --- | --- | --- | --- |
| S0 | DONE | Establish an evidence-based simplification baseline. | Review found 115,134 lines under `src/harness/re_v2`, oversized orchestration methods in squad/delivery, and a dual CLI. Representative controller suite: 274 passed. | Review and ordered control queue exist. |
| S1 | DONE | Remove retired SOAR execution without removing shared memory and security utilities. | 24,911 lines deleted; `src/codegen` reduced to nine retained utility files; 535 focused tests and 10,003 full-unit tests passed. | No SOAR execution entry point, installer option, strategy, overlay, or active execution test remains; retained utility consumers and normal delivery tests pass. |
| S2 | DONE | Make controlled delivery the sole supported delivery implementation. | Feature switch, feature-off execution, legacy runner/prompt modules, raw build command, and `build-*` phase graph are removed; 357 focused and 9,804 full-unit tests passed. | Current guidance names controlled delivery only; focused and repository verification gates pass. |
| S3 | DONE | Complete the Typer CLI cutover. | Executable route recount: 104 public commands, all 104 using modular front doors, 23 hidden routes, and zero direct public or hidden `_legacy_cli()` consumers. Final structural gate: 27 passed. Repository gate against `bfdb744c`: 9,853 passed, 0 skipped, 11,438 deselected, 0 failures in 2,121.92s. `echelon.re_service` is the single quarantine adapter; `echelon.cli` retains the RE protocol kernel for S6. | User-facing commands invoke typed application services; compatibility aliases are isolated; the remaining RE kernel dependency is contained behind one named facade scheduled for S6. |
| S4 | DONE | Remove the abandoned strategy dimension and decompose single-run Delivery orchestration around its durable checkpoints. | Durable-step decomposition complete: focused acceptance passed 287 tests; final repository gate passed 9,832 tests with 0 failures. `_run_delivery` is 28 lines and `_run_loop_inner` is 159 lines. | Delivery has no strategy option or identity; one `DeliveryController` owns one run and Ralph performs one explicit durable step at a time; focused delivery suite passes. |
| S5 | DONE | Reduce spec authoring to one controller kernel and publication boundary. | Current state version 1 has one durable `pending_spec_step`, one effect/recovery kernel, and no historical-run migration. The post-cutover recovery checklist is ported and its replacement 9,832-test repository gate passed. | One recover-plan-execute-commit path owns transitions and effects; redundant transactional representations are removed. |
| STAB-1 | ACTIVE | Close provider-dispatch finalization and operational workspace acceptance before another refactor. | Six provider-finalization implementation commits are present, followed by review/dry-run corrections and 15 Delivery/fulfillment fixes from live execution. Current `main` has no repository-bound receipt after `62a43bdf`. Plan: [`2026-09-27-provider-finalization-workspace-acceptance.md`](superpowers/plans/2026-09-27-provider-finalization-workspace-acceptance.md). | The preserved smoke remains immutable diagnostic evidence; one newly initialized Phase A → publication → Delivery run completes with a resume; exact final commit/tree passes focused, unit, complete-suite, dry-run/install, and range-review gates; receipt is recorded and checkpoint pushed. |
| S6 | PENDING | Consolidate RE onto one current executable protocol. | Protocols 2.2 through 2.8 and the older extraction lifecycle remain represented in the RE kernel retained in `echelon.cli`; `echelon.re_service` is its single active route adapter. | Historical runs enter through migration/import adapters; current execution does not inherit historical controllers. |
| S7 | PENDING | Remove residual compatibility code and break large import cycles. | Static import analysis found production cycles far larger than a locally understandable component. | No production strongly connected import component contains more than five modules; full repository verification passes. |

## S1 Work Queue

- [x] Inventory every `src/codegen` import and classify it as active shared
  utility, rejected compatibility entry point, or dead execution code.
- [x] Inventory CLI, installer, strategy, documentation, and test references to
  SOAR/codegen execution.
- [x] Define the exact retained utility boundary before deleting files.
- [x] Remove execution entry points, installer flags, strategies, and tests that
  exist only to support retired execution.
- [x] Update command help and documentation to describe only supported paths.
- [x] Run focused utility, CLI, spec, and delivery tests.
- [x] Run the repository verification gate and record its result below.

## Evidence Log

| Date | Milestone | Evidence |
| --- | --- | --- |
| 2026-09-21 | S0 | `.venv/bin/python -m pytest -q tests/unit/test_coordinator.py tests/unit/test_re_controller.py tests/unit/test_re_lifecycle.py tests/unit/test_re_v2_controller.py` — 274 passed in 24.32s. |
| 2026-09-21 | S1 | Activated. Execution is already fail-closed through `src/codegen/retirement.py`; deletion inventory is next. |
| 2026-09-21 | S1 | Production imports reach seven current `codegen` modules: five shared memory modules, the secret scrubber, and the retirement guard. The guard is deletion-only; the scrubber's only execution dependency is the credential deny-list in `codegen.soar.smem_writer`, which the S1 plan extracts before deleting the execution tree. |
| 2026-09-21 | S1 | Completed. Compared with control baseline `51dbfdc0`: 172 files changed, 692 additions, 24,911 deletions (net -24,219). `src/codegen` now contains exactly five memory modules plus their initializer and three security files. Active-surface search found no retired execution command, installer, strategy, overlay, prompt, or runtime reference. |
| 2026-09-21 | S1 | Focused S1 suite: 535 passed in 31.22s. Repository merge verification: 10,003 passed, 11,468 deselected in 32m44s; receipt `tests/reports/merge-verification/receipt-937065b02b85-cb24a9c75e4b46b6be160e5ba83fd45e.json`. |
| 2026-09-21 | S2 | Activated after all S1 exit checks passed. Next action: inventory the controlled-delivery feature switch and feature-off call graph before changing behavior. |
| 2026-09-21 | S2 | Inventory found the switch in config parsing/templates, coordinator prompt selection/token accounting, Ralph build/feedback/recovery branches, raw CLI dispatch, current guidance, and 11 focused test files. Hard-cutover design approved: `docs/superpowers/specs/2026-09-21-controlled-delivery-hard-cutover-design.md`. |
| 2026-09-21 | S2 | Legacy execution deletion complete: removed the runner/prompt modules, raw Prosaic build command, and `build-*` phase graph. Task 4 acceptance ran 811 cases: 809 passed; the two failures are prompt-governance drift in unchanged producer/reviewer and WHY1 prompt files, not controlled-delivery regressions. Active production search found no retired delivery import or runtime reference. |
| 2026-09-21 | S2 | Current guidance now names `echelon delivery run <id>` as the sole Phase B entry point. Active-surface search found no feature flag or retired runner/prompt identifier; remaining `echelon build` references are the validated internal strategy identifier or the explicit CLI migration error. Focused S2 gate: 357 passed in 115.13s. |
| 2026-09-21 | S2 | Completed. Repository merge verification against `42497d25`: 9,804 passed, 11,394 deselected in 29m19s; receipt `tests/reports/merge-verification/receipt-84c904c47e9a-c8590de8e92846b68497e6bdc72eb549.json`. |
| 2026-09-21 | S3 | Activated after all S2 exit checks passed. Next action: inventory every public Typer command's delegation into `cli.py` and classify typed-service, compatibility, and dead paths before changing behavior. |
| 2026-09-21 | S3 | Route inventory completed: 107 public commands, with 52 modular and 55 delegated into `cli.py`; 22 hidden commands include compatibility aliases, two retired error-only routes, and active internal RE entry points. Inventory: `docs/findings/2026-09-21-typer-route-inventory.md`. |
| 2026-09-21 | S3 | Benchmark slice implemented: `benchmark list/show/run` call typed functions in `echelon.benchmark`, `_cmd_benchmark` is deleted from `cli.py`, 37 benchmark tests pass, and the 1,054-test CLI-focused gate passes. |
| 2026-09-21 | S3 | Benchmark slice repository gates: 9,804 passed and 11,398 deselected on the feature branch in 32m13s and again on merged `main` in 32m36s. S3 remains active; `stack` is the next cutover slice. |
| 2026-09-22 | S3 | Stack slice implemented: all eight `stack` commands call `echelon.stack_service`, the 586-line private stack handler block is deleted from `cli.py`, 127 focused stack tests pass, and the 1,024-test CLI-focused gate passes. S3 remains active; `workspace` is the next cutover slice. |
| 2026-09-22 | S3 | Stack slice repository gate: 9,816 passed and 11,398 deselected in 30m00s on the feature branch. |
| 2026-09-22 | S3 | Workspace slice implemented: all five public `workspace` commands call `echelon.workspace_service`; initialization, doctor, migration, and source synchronization no longer live in `cli.py`; 296 focused workspace tests and the 1,022-test CLI-focused gate pass. S3 remains active; `phase` and `version` are next. |
| 2026-09-22 | S3 | Workspace slice repository gate: 9,820 passed and 11,394 deselected in 31m58s on the feature branch. |
| 2026-09-22 | S3 | Phase/version slice implemented: `phase list/run` call `echelon.phase_service`, `_cmd_phase` is deleted, version output uses `echelon.version`, release tooling updates the new canonical version file, 109 focused tests and the 1,026-test CLI gate pass. Shared phase replay helpers remain in `cli.py` until the active spec slice. S3 remains active; compatibility and retired routes are next. |
| 2026-09-22 | S3 | Phase/version slice repository gate: 9,822 passed and 11,396 deselected in 31m32s on the feature branch. |
| 2026-09-22 | S3 | Compatibility cleanup implemented: hidden retired `build` and `cicd` routes and their private handler branches are deleted; root and hidden `harness` aliases forward through canonical commands, with only `review` retained behind an explicit compatibility adapter. The 90-test Typer contract suite and 1,093-test CLI regression gate pass. S3 remains active; `spec` is next. |
| 2026-09-22 | S3 | Compatibility cleanup repository gate: 9,822 passed and 11,409 deselected in 34m14s on the feature branch. |
| 2026-09-22 | S3 | Spec service cutover implemented in `025ea318` and `51e89892`: all 16 active `spec` routes now call typed services, Phase A run/recovery ownership moved to `echelon.spec_service`, shared manual phase replay consumes its public recovery helpers, and the hidden `spec target` mutation guard is isolated there. Focused verification: 1,492 passed across the planned Spec/Phase A partitions. The CLI regression gate had 2,523 applicable passes; its sole remaining missing-template failure reproduced unchanged on the base branch. |
| 2026-09-22 | S3 | Spec service repository gate: 9,822 passed and 11,421 deselected in 29m30s; receipt `tests/reports/merge-verification/receipt-51e89892a0d9-07ba7c1ebc08415f8439c88672ce73e6.json`. S3 remains active; active `delivery` workflows are next. |
| 2026-09-23 | S3 | Delivery service cutover completed in `a85def96`, `f9ad8087`, `d8bd6a92`, and `bc64acae`; `0741dd4c` moved the lifecycle ownership validator. Final review fix `cdb1a4d3` passes the API project root to run/recovery capability checks, moves the remaining Delivery-only renderer, removes eight CLI helper re-exports, and migrates the remaining integration/runtime test imports. All nine active Delivery routes use `echelon.delivery_service`; `delivery status` retains its facade with a service-owned kernel. RED: three explicit-root regressions and the ownership guard failed as intended. GREEN: 38 affected tests (including all 17 boundary cases) passed in 13.66s; 302 focused Delivery tests passed in 58.32s. Executable-tree recount: 104 public, 23 hidden, 9 public direct `_legacy_cli()` consumers, 95 modular public routes; S3 stays ACTIVE with RE next. The single final repository gate against `3abca341` tested commit `cdb1a4d310ed7bf39358ee71284ebedf5a8f465a`, tree `b2b80184eab739396535ae402d800dc8985e8eb2`: 9,822 passed, 0 skipped, 11,438 deselected, 0 failures in 1,773.29s (29m33.29s); receipt subprocess duration 1,775,535ms, exit 0. Replacement receipt: `tests/reports/merge-verification/receipt-cdb1a4d310ed-88781f07aeae4d69a0049ac35bed75fb.json`, bound to the tested code/test commit before the evidence commit. Earlier broad CLI gate evidence remains historical: 1,672 passed and 1 baseline-reproduced failure in 274.71s; not rerun in this wave. The active RE facade is next and final; RE protocol consolidation remains assigned to S6. |
| 2026-09-23 | S3 | Completed. All nine public and two hidden RE routes use the `echelon.re_service` typed quarantine facade; `echelon.cli` retains the protocol kernel for S6. Final review correction `3e648dc5` restores malformed `re resume` compatibility by letting the unchanged kernel validate through the facade: RED was 4 output-contract failures, GREEN was 4 passed in 10.46s; adding the missing module marker changed the boundary selection from 27 deselected/exit 5 to 27 passed in 10.36s. The focused RE/CLI suite passed 275 tests in 38.83s. Structural acceptance still has no `_legacy_cli()` call in `src/echelon/cli_app.py`; executable-tree recount remains 104 public, 23 hidden, zero direct public or hidden `_legacy_cli()` consumers, and 104 modular public routes. The single repository gate against `bfdb744c` tested commit `3e648dc5ab1907b07c3e5cf9922381d8b9e697bc`, tree `21b0b54adcb157d18ff7fa59822735e8f495de4f`: 9,853 passed, 0 skipped, 11,438 deselected, 0 failures in 2,121.92s (35m21.92s); receipt subprocess duration 2,124,409ms, exit 0. Receipt: `tests/reports/merge-verification/receipt-3e648dc5ab19-9a15640fb46a41918b2d6d2807f60395.json`. |
| 2026-09-23 | S4 | Activated after all S3 exit checks passed. Next action: inventory the durable Delivery controller steps before any decomposition. RE protocol consolidation remains assigned to S6. |
| 2026-09-23 | S4 | Inventory confirmed that every active Delivery command reaches `StrategyCoordinator`, but production always uses its single built-in `default` path. The coordinator nevertheless owns state initialization/resume, phase routing, result comparison, budget splitting, thread fan-out, peer cancellation, and finalization; its `_run_strategy` method is approximately 1,000 lines, as is `RalphController._run_loop_inner`. Approved hard cutover removes the Delivery strategy concept entirely, does not support historical strategy state, introduces one run-scoped `DeliveryController`, and then extracts one existing durable checkpoint at a time. Design: `docs/superpowers/specs/2026-09-23-single-delivery-controller-design.md`. |
| 2026-09-23 | S4 | Single-run cutover implementation plan written as `docs/superpowers/plans/2026-09-23-single-delivery-controller-cutover.md`. It separates the deletion-first cutover from the later Ralph loop decomposition so each has an independent green repository gate. |
| 2026-09-23 | S4 | Single-run cutover implemented. `StrategyCoordinator`, strategy loading, budget fan-out, peer cancellation, comparison results, per-strategy state, and strategy artifact identity are removed. Focused evidence: 224 executable cutover tests, 354 artifact/recovery tests, 163 Ralph/controller tests, and 212 adjacent state/topology/provider tests passed. Next action after the repository gate: write and approve the checkpoint-led Ralph durable-step decomposition plan; S4 remains ACTIVE. |
| 2026-09-23 | S4 | Single-run cutover repository gate against `52f30d16` tested commit `39fc417f1078a2852be5ce03e61d80f623f1245f`, tree `4b1120fab4d9155c00fced1c29f1def8963d2e2b`: 9,830 passed, 11,429 deselected, 0 failures in 2,139.83s (35m39.83s); receipt subprocess duration 2,142,461ms, exit 0. Receipt: `tests/reports/merge-verification/receipt-39fc417f1078-d1fbebfedd3b45c88654fcef7538461b.json`. The next S4 action is the checkpoint-led Ralph decomposition plan; S4 remains ACTIVE. |
| 2026-09-23 | S4 | Checkpoint-led Ralph decomposition design written as `docs/superpowers/specs/2026-09-23-ralph-durable-step-decomposition-design.md`. It preserves the fixed `delivery.json` contract and extracts existing pending-operation recovery, controlled slice, progress, verification, review re-entry, publication, and finalization boundaries in place before any file split. Next action: review the design, then write the task-by-task implementation plan. |
| 2026-09-23 | S4 | Task-by-task Ralph durable-step implementation plan written as `docs/superpowers/plans/2026-09-23-ralph-durable-step-decomposition.md`. Ten independently reviewable tasks extract the existing checkpoints in order, flatten the two orchestration methods, and finish with a repository-bound verification receipt. Next action: approve an execution mode and execute Task 1. |
| 2026-09-24 | S4 | Durable-step implementation complete through Task 9. Named boundaries now cover pending-slice recovery, iteration preparation, controlled dispatch, progress checkpointing, candidate verification, run/resume planning, bounded review re-entry, and verified-publication dispatch. Focused evidence: 47 review re-entry tests and 259 combined Delivery/Ralph tests passed; `_run_delivery` is 28 lines and `_run_loop_inner` is 159 lines. S4 remains ACTIVE until the repository gate records its receipt. |
| 2026-09-24 | S4 | Completed. Focused acceptance passed 287 tests in 45.28s. Repository gate against `7af823a9` tested commit `e76c937cdfbc208171cd0f57c70bf561ae276fc4`, tree `11098e4604a7f87866683c65a87bc52159485aca`: 9,830 passed, 11,429 deselected, 0 failures in 1,830.06s (30m30.06s); receipt subprocess duration 1,832,485ms, exit 0. Receipt: `tests/reports/merge-verification/receipt-e76c937cdfbc-fa239e6dbc824858826ec7d401d73f61.json`. |
| 2026-09-24 | S4 | Final review correction `97de0583` restores publication recovery before pending review repair: successful recovery skips Ralph, while failed recovery falls through to exactly one repair dispatch. RED reproduced the skipped recovery; GREEN covered both paths, and the adjacent recovery suite passed 95 tests in 31.87s. Replacement repository gate against `7af823a9` tested commit `97de0583b0908c440efb312388b4157ed607ddd1`, tree `ae22820d10245e38bba87b7e9f92053023fec167`: 9,832 passed, 11,429 deselected, 0 failures in 2,085.20s (34m45.20s); receipt subprocess duration 2,087,770ms, exit 0. Replacement receipt: `tests/reports/merge-verification/receipt-97de0583b090-03ee38f46e204ee1a8d6f5abdcacd829.json`. The earlier receipt remains historical. |
| 2026-09-24 | S5 | Activated after all S4 exit checks passed. Next action: inventory the active spec-authoring recover-plan-execute-commit path and its publication boundary before changing behavior. |
| 2026-09-24 | S5 | Inventory found one routed result represented by a prepared result, routing decision, two pending state markers, two failure lifecycles, two outbox identities, an effect plan, receipts, and final dispatch state across approximately 42,900 lines of active spec-controller code. Approved direction: current-version runs only, one durable `pending_spec_step`, one recover-plan-execute-commit kernel, and publication as one step effect while retaining the existing descriptor-safe publication primitive. Design: `docs/superpowers/specs/2026-09-24-spec-step-kernel-design.md`. Focused pre-design baseline: 513 passed in 382.37s. Next action: review the written design, then write the implementation plan. |
| 2026-09-24 | S5 | Implementation plan written as `docs/superpowers/plans/2026-09-24-spec-step-kernel.md`. Eleven independently green tasks establish the current-only state boundary, sealed step documents, atomic transitions, one recovery kernel, effect adapters, four cutovers, deletion guards, controller flattening, and repository-bound verification. Next action: review the plan and select Native or subagent-driven execution. |
| 2026-09-25 | S5 | Implementation tasks 1–10 complete. Fresh Phase A state is version 1; `pending_spec_step` is the only durable in-flight step authority; routed, terminal, manual, human-resolution, and managed paths use the common recovery kernel; publication remains a descriptor-safe step effect. Historical and unversioned runs require reset rather than migration. Structural ownership and focused current-run suites pass; final repository-bound verification is next. |
| 2026-09-25 | S5 | Completed. Candidate `f8c76b4db6e3b2d0778ca7095ec9ac1ae7e5b7b0`, tree `a64a7aa7506f78b589a6ff9841127c9f638d3c62`, was verified against implementation base `b24259611015ca9904c97e448acc823ce49bb95f`. Focused evidence includes the 1,056-test structural/kernel/current-run gate plus routed/manual/blocked/terminal/recovery, discovery-completion, and managed checkpoint source-chain checks. Repository merge verification ran `pytest -q -m unit`: 9,832 passed, 11,321 deselected, 0 failures in 2,045.61s (34m05s). Receipt: `tests/reports/merge-verification/receipt-f8c76b4db6e3-a83e939a427548e4ace3132e585e13cf.json`. S6 remains pending. |
| 2026-09-25 | S5 | Post-cutover recovery correction ported from `origin/codex/spec-recovery-regressions` without restoring retired protocols. Current behavior preserves resolved decision authority during issue repair, delegates `pending_spec_step` replay to the existing controller kernel, persists unsealed mode overrides through `SquadStateStore`, and renders actionable Phase 3 blockers. TDD: five new tests failed for the diagnosed reasons, then all six checklist tests passed. Adjacent gates: 112 continuation/resolution tests, 20 spec-step kernel/state tests, 6 controller crash-recovery cases, and 50 service-boundary/status tests passed. Replacement repository gate against `46ef1d1c74a31fbd22ac27254a7a8840f5a9c198` tested candidate `62a43bdfe655705594b32c5354e7ad8b232dc746`, tree `eed7082adbdf6c19ca6ed0a41f9846a0aeb18bf6`: 9,832 passed, 11,326 deselected, 0 failures in 1,960.40s (32m40s). Receipt: `tests/reports/merge-verification/receipt-62a43bdfe655-40ec9f724acf40839484d266f94e1174.json`. S6 remains pending. |

## S2 Work Queue

- [x] Inventory the feature switch and feature-off call graph.
- [x] Approve the hard-cutover design and preserved recovery boundary.
- [x] Write and review the implementation plan.
- [x] Remove configuration, CLI, and coordinator branching.
- [x] Remove Ralph's legacy build, feedback, and recovery paths.
- [x] Delete legacy delivery runner and prompt-resolution implementation.
- [x] Update current documentation and focused tests.
- [x] Run focused delivery verification.
- [x] Run the repository verification gate and record its result.

## S3 Work Queue

- [x] Inventory every public Typer command and its delegated `cli.py` entry point.
- [x] Classify each route as typed service, compatibility alias, or dead path.
- [x] Define and approve the minimum cutover boundary before editing behavior.
- [x] Move active command workflows behind typed application services.
- [x] Isolate compatibility aliases from active routing.
- [x] Run focused CLI verification.
- [x] Run the repository verification gate and record its result.

### S3 Cutover Order

- [x] Cut over `benchmark list/show/run` and delete `_cmd_benchmark`.
- [x] Cut over `stack list/detect/preflight/provision/enable/disable/select/selected`.
- [x] Cut over `workspace` initialization, doctor, migration, and source sync.
- [x] Cut over `phase` and `version`.
- [x] Delete retired routes and isolate root/`harness` compatibility aliases.
- [x] Cut over active `spec` workflows.
- [x] Cut over active `delivery` workflows without changing the state contract.
- [x] Put active `re` workflows behind a typed facade; leave protocol consolidation to S6.

## S4 Work Queue

- [x] Inventory the active Delivery call path and durable controller checkpoints.
- [x] Confirm that multi-strategy execution is not a supported product mode.
- [x] Approve the single-run hard-cutover boundary and historical-state policy.
- [x] Review and approve the written S4 design.
- [x] Write the single-run cutover implementation plan.
- [x] Review and approve the single-run cutover implementation plan.
- [x] Write and approve the checkpoint-led Ralph decomposition plan after the cutover lands.
- [x] Remove Delivery strategy inputs, parsing, loading, fan-out, comparison, and cancellation.
- [x] Replace per-strategy state with one run-scoped state and controller.
- [x] Extract controller/Ralph steps one durable checkpoint at a time.
- [x] Update current documentation and run focused Delivery verification.
- [x] Run the repository verification gate and record its result.

## S5 Work Queue

- [x] Inventory the active Phase A state, routing, completion, publication, and recovery protocols.
- [x] Approve the current-only state policy and single durable-step architecture.
- [x] Write and review the detailed design.
- [x] Write the task-by-task implementation plan.
- [x] Review and approve the implementation plan and execution mode.
- [x] Enforce the current Phase A state version for fresh runs only.
- [x] Add sealed step documents, atomic state transitions, and the single recovery kernel.
- [x] Adapt existing effects while retaining descriptor-safe publication.
- [x] Cut over routed, manual, terminal, human-resolution, and managed completion paths.
- [x] Delete the retired completion/publication protocols and add structural ownership guards.
- [x] Flatten the controller around one current-phase step loop.
- [x] Update current documentation, run focused verification, and record the repository receipt.

## STAB-1 Work Queue

- [x] Establish the stabilization milestone and freeze S6/S7.
- [x] Snapshot the published Browser App Gates into new Delivery phase selection
  even when no stack matches (`a043a63c`; 68 Delivery controller tests passed).
- [x] Reject visual verification that changes bounded candidate content before
  issuing a passing receipt (`6a2de222`; 93 Delivery/visual tests passed).
- [ ] Give browser-required tasks a controller-owned browser-evidence handoff
  before slice acceptance; keep provider task ownership and reviewer verdicts.
  `fd54cf29` returns a retained proposal to the same task; a live Docker
  Playwright/host-scope probe captured one image without changing its candidate.
  The preserved rugby demo's Chromium test passes but declares no snapshot, so
  capture yields no image. The slice now retains that non-approving observation,
  tells the same implementer to add a snapshot assertion, and allows one bounded
  recapture; absent or repeatedly empty capture cannot pass to reviewers. A live
  isolated Docker rerun confirmed Playwright passes with zero images and leaves
  the preserved demo unchanged. An installed-workspace run remains pending.
- [x] Run browser verification from a disposable container copy of a read-only
  candidate mount; retain evidence outside the product worktree (`d64b7a16`;
  235 adjacent tests and two real-Docker isolation/runtime smokes passed).
- [ ] Define an explicit visual-review decision for retained images before
  T-012 can count as visually accepted; a screenshot receipt alone is not review.
- [x] Preserve the blocked 12-task Delivery smoke as diagnostic evidence without
  manually editing the generated product worktree.
- [ ] Run one newly initialized Phase A → publication → Delivery acceptance with resume.
- [ ] Run final focused, unit, complete-suite, dry-run/install, and range-review gates.
- [ ] Record a receipt for the exact final commit/tree and close provider-finalization tracking.
- [ ] Complete one fresh whole-range review and push the verified checkpoint.

The preserved rugby-demo product worktree is evidence only. Do not hand-edit
its source, tests, screenshots, or baselines. Product changes, if any, must be
made by Echelon's Delivery provider after the controller supplies scoped
evidence; no historical-run migration is required.

## Drift Guard

Until S7 is complete:

- Do not add another RE protocol generation.
- Do not add a third CLI dispatch layer.
- Do not add new behavior to a path scheduled for deletion.
- Do not create a general framework before two active consumers need it.
- Do not mark a milestone done without recording its verification evidence.
