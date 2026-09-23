# Echelon Simplification Control

**Rule:** one `ACTIVE` milestone at a time. Finish or explicitly block it before
starting another.

**Design:**
[`2026-09-21-harness-simplification-control-design.md`](superpowers/specs/2026-09-21-harness-simplification-control-design.md)

**Current milestone:** S3 — Complete the Typer CLI cutover

## Status

| ID | Status | Outcome | Current evidence | Exit check |
| --- | --- | --- | --- | --- |
| S0 | DONE | Establish an evidence-based simplification baseline. | Review found 115,134 lines under `src/harness/re_v2`, oversized orchestration methods in squad/delivery, and a dual CLI. Representative controller suite: 274 passed. | Review and ordered control queue exist. |
| S1 | DONE | Remove retired SOAR execution without removing shared memory and security utilities. | 24,911 lines deleted; `src/codegen` reduced to nine retained utility files; 535 focused tests and 10,003 full-unit tests passed. | No SOAR execution entry point, installer option, strategy, overlay, or active execution test remains; retained utility consumers and normal delivery tests pass. |
| S2 | DONE | Make controlled delivery the sole supported delivery implementation. | Feature switch, feature-off execution, legacy runner/prompt modules, raw build command, and `build-*` phase graph are removed; 357 focused and 9,804 full-unit tests passed. | Current guidance names controlled delivery only; focused and repository verification gates pass. |
| S3 | ACTIVE | Complete the Typer CLI cutover. | Of 107 public commands, 96 now use modular services and 11 still delegate into `cli.py`. Benchmark, stack, workspace, phase/version, spec, and delivery workflows are cut over; retired routes are deleted and compatibility aliases are isolated. The active RE facade is next and final. | User-facing commands invoke typed application services; compatibility aliases are isolated; `cli.py` no longer owns active command workflows. |
| S4 | PENDING | Decompose delivery orchestration without changing its state contract. | `RalphController._run_loop_inner` and `StrategyCoordinator._run_strategy` each exceed 1,000 lines. | Coordinator schedules strategies only; Ralph performs one explicit durable step at a time; focused delivery suite passes. |
| S5 | PENDING | Reduce spec authoring to one controller kernel and publication boundary. | Squad routing, state, recovery, completion, and publication form a large circular dependency component. | One recover-plan-execute-commit path owns transitions and effects; redundant transactional representations are removed. |
| S6 | PENDING | Consolidate RE onto one current executable protocol. | Protocols 2.2 through 2.8 and the older extraction lifecycle remain represented in executable controller code. | Historical runs enter through migration/import adapters; current execution does not inherit historical controllers. |
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
| 2026-09-23 | S3 | Delivery service cutover completed in `a85def96`, `f9ad8087`, `d8bd6a92`, and `bc64acae`: all nine active Delivery routes use `echelon.delivery_service`; `delivery status` retains its `echelon.delivery_status` facade with a service-owned kernel. Focused Delivery verification: 287 passed in 57.91s; structural boundary verification: 13 passed in 10.42s. CLI regression gate: 1,672 passed and 1 verified pre-existing failure in 4m34s. Repository merge verification against `3abca341`: 9,821 passed, 0 skipped, 11,434 deselected, and 1 ownership-validator failure in 29m32.63s (`TestSpecCompletion.test_cli_writes_in_progress_at_harness_run_start` still expects the moved `cli.py` state write); receipt `tests/reports/merge-verification/receipt-bc64acae6239-be8583363d484eb19e91136bc30f3a43.json`. S3 remains ACTIVE; the active RE facade is next and final, while RE protocol consolidation remains assigned to S6. |

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
- [ ] Move active command workflows behind typed application services.
- [x] Isolate compatibility aliases from active routing.
- [ ] Run focused CLI verification.
- [ ] Run the repository verification gate and record its result.

### S3 Cutover Order

- [x] Cut over `benchmark list/show/run` and delete `_cmd_benchmark`.
- [x] Cut over `stack list/detect/preflight/provision/enable/disable/select/selected`.
- [x] Cut over `workspace` initialization, doctor, migration, and source sync.
- [x] Cut over `phase` and `version`.
- [x] Delete retired routes and isolate root/`harness` compatibility aliases.
- [x] Cut over active `spec` workflows.
- [x] Cut over active `delivery` workflows without changing the state contract.
- [ ] Put active `re` workflows behind a typed facade; leave protocol consolidation to S6.

## Drift Guard

Until S7 is complete:

- Do not add another RE protocol generation.
- Do not add a third CLI dispatch layer.
- Do not add new behavior to a path scheduled for deletion.
- Do not create a general framework before two active consumers need it.
- Do not mark a milestone done without recording its verification evidence.
