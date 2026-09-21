# Echelon Simplification Control

**Rule:** one `ACTIVE` milestone at a time. Finish or explicitly block it before
starting another.

**Design:**
[`2026-09-21-harness-simplification-control-design.md`](superpowers/specs/2026-09-21-harness-simplification-control-design.md)

**Current milestone:** S2 — Make controlled delivery the sole supported path

## Status

| ID | Status | Outcome | Current evidence | Exit check |
| --- | --- | --- | --- | --- |
| S0 | DONE | Establish an evidence-based simplification baseline. | Review found 115,134 lines under `src/harness/re_v2`, oversized orchestration methods in squad/delivery, and a dual CLI. Representative controller suite: 274 passed. | Review and ordered control queue exist. |
| S1 | DONE | Remove retired SOAR execution without removing shared memory and security utilities. | 24,911 lines deleted; `src/codegen` reduced to nine retained utility files; 535 focused tests and 10,003 full-unit tests passed. | No SOAR execution entry point, installer option, strategy, overlay, or active execution test remains; retained utility consumers and normal delivery tests pass. |
| S2 | ACTIVE | Make controlled delivery the sole supported delivery implementation. | Feature switch, feature-off execution, legacy runner/prompt modules, raw build command, and `build-*` phase graph are removed. | Current guidance names controlled delivery only; focused and repository verification gates pass. |
| S3 | PENDING | Complete the Typer CLI cutover. | `cli_app.py` is the front door but still delegates many commands to private functions in the 22,237-line `cli.py`. | User-facing commands invoke typed application services; compatibility aliases are isolated; `cli.py` no longer owns active command workflows. |
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

## S2 Work Queue

- [x] Inventory the feature switch and feature-off call graph.
- [x] Approve the hard-cutover design and preserved recovery boundary.
- [x] Write and review the implementation plan.
- [x] Remove configuration, CLI, and coordinator branching.
- [x] Remove Ralph's legacy build, feedback, and recovery paths.
- [x] Delete legacy delivery runner and prompt-resolution implementation.
- [ ] Update current documentation and focused tests.
- [ ] Run focused delivery verification.
- [ ] Run the repository verification gate and record its result.

## Drift Guard

Until S7 is complete:

- Do not add another RE protocol generation.
- Do not add a third CLI dispatch layer.
- Do not add new behavior to a path scheduled for deletion.
- Do not create a general framework before two active consumers need it.
- Do not mark a milestone done without recording its verification evidence.
