# Echelon Simplification Control

**Rule:** one `ACTIVE` milestone at a time. Finish or explicitly block it before
starting another.

**Design:**
[`2026-09-21-harness-simplification-control-design.md`](superpowers/specs/2026-09-21-harness-simplification-control-design.md)

**Current milestone:** S5 — Reduce spec authoring to one controller kernel and publication boundary

## Status

| ID | Status | Outcome | Current evidence | Exit check |
| --- | --- | --- | --- | --- |
| S0 | DONE | Establish an evidence-based simplification baseline. | Review found 115,134 lines under `src/harness/re_v2`, oversized orchestration methods in squad/delivery, and a dual CLI. Representative controller suite: 274 passed. | Review and ordered control queue exist. |
| S1 | DONE | Remove retired SOAR execution without removing shared memory and security utilities. | 24,911 lines deleted; `src/codegen` reduced to nine retained utility files; 535 focused tests and 10,003 full-unit tests passed. | No SOAR execution entry point, installer option, strategy, overlay, or active execution test remains; retained utility consumers and normal delivery tests pass. |
| S2 | DONE | Make controlled delivery the sole supported delivery implementation. | Feature switch, feature-off execution, legacy runner/prompt modules, raw build command, and `build-*` phase graph are removed; 357 focused and 9,804 full-unit tests passed. | Current guidance names controlled delivery only; focused and repository verification gates pass. |
| S3 | DONE | Complete the Typer CLI cutover. | Executable route recount: 104 public commands, all 104 using modular front doors, 23 hidden routes, and zero direct public or hidden `_legacy_cli()` consumers. Final structural gate: 27 passed. Repository gate against `bfdb744c`: 9,853 passed, 0 skipped, 11,438 deselected, 0 failures in 2,121.92s. `echelon.re_service` is the single quarantine adapter; `echelon.cli` retains the RE protocol kernel for S6. | User-facing commands invoke typed application services; compatibility aliases are isolated; the remaining RE kernel dependency is contained behind one named facade scheduled for S6. |
| S4 | DONE | Remove the abandoned strategy dimension and decompose single-run Delivery orchestration around its durable checkpoints. | Durable-step decomposition complete: focused acceptance passed 287 tests; final repository gate passed 9,832 tests with 0 failures. `_run_delivery` is 28 lines and `_run_loop_inner` is 159 lines. | Delivery has no strategy option or identity; one `DeliveryController` owns one run and Ralph performs one explicit durable step at a time; focused delivery suite passes. |
| S5 | ACTIVE | Reduce spec authoring to one controller kernel and publication boundary. | Squad routing, state, recovery, completion, and publication form a large circular dependency component. Next: inventory the active recover-plan-execute-commit path before changing behavior. | One recover-plan-execute-commit path owns transitions and effects; redundant transactional representations are removed. |
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

## Drift Guard

Until S7 is complete:

- Do not add another RE protocol generation.
- Do not add a third CLI dispatch layer.
- Do not add new behavior to a path scheduled for deletion.
- Do not create a general framework before two active consumers need it.
- Do not mark a milestone done without recording its verification evidence.
