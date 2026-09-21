# Echelon Simplification Control

**Rule:** one `ACTIVE` milestone at a time. Finish or explicitly block it before
starting another.

**Design:**
[`2026-09-21-harness-simplification-control-design.md`](superpowers/specs/2026-09-21-harness-simplification-control-design.md)

**Current milestone:** S1 — Remove retired SOAR execution

## Status

| ID | Status | Outcome | Current evidence | Exit check |
| --- | --- | --- | --- | --- |
| S0 | DONE | Establish an evidence-based simplification baseline. | Review found 115,134 lines under `src/harness/re_v2`, oversized orchestration methods in squad/delivery, and a dual CLI. Representative controller suite: 274 passed. | Review and ordered control queue exist. |
| S1 | ACTIVE | Remove retired SOAR execution without removing shared memory or graph utilities. | Execution is already rejected; README and AGENTS describe it as disabled pending removal. | No SOAR execution entry point, installer option, strategy, or active execution test remains; retained utility consumers and normal delivery tests pass. |
| S2 | PENDING | Make controlled delivery the sole supported delivery implementation. | Controller exists behind `llm.features.delivery_gate_controller`; default remains false. | Feature switch and feature-off path are removed; existing controlled-delivery, continuation, repair, verification, and review tests pass. |
| S3 | PENDING | Complete the Typer CLI cutover. | `cli_app.py` is the front door but still delegates many commands to private functions in the 22,237-line `cli.py`. | User-facing commands invoke typed application services; compatibility aliases are isolated; `cli.py` no longer owns active command workflows. |
| S4 | PENDING | Decompose delivery orchestration without changing its state contract. | `RalphController._run_loop_inner` and `StrategyCoordinator._run_strategy` each exceed 1,000 lines. | Coordinator schedules strategies only; Ralph performs one explicit durable step at a time; focused delivery suite passes. |
| S5 | PENDING | Reduce spec authoring to one controller kernel and publication boundary. | Squad routing, state, recovery, completion, and publication form a large circular dependency component. | One recover-plan-execute-commit path owns transitions and effects; redundant transactional representations are removed. |
| S6 | PENDING | Consolidate RE onto one current executable protocol. | Protocols 2.2 through 2.8 and the older extraction lifecycle remain represented in executable controller code. | Historical runs enter through migration/import adapters; current execution does not inherit historical controllers. |
| S7 | PENDING | Remove residual compatibility code and break large import cycles. | Static import analysis found production cycles far larger than a locally understandable component. | No production strongly connected import component contains more than five modules; full repository verification passes. |

## S1 Work Queue

- [ ] Inventory every `src/codegen` import and classify it as active shared
  utility, rejected compatibility entry point, or dead execution code.
- [ ] Inventory CLI, installer, strategy, documentation, and test references to
  SOAR/codegen execution.
- [ ] Define the exact retained utility boundary before deleting files.
- [ ] Remove execution entry points, installer flags, strategies, and tests that
  exist only to support retired execution.
- [ ] Update command help and documentation to describe only supported paths.
- [ ] Run focused utility, CLI, spec, and delivery tests.
- [ ] Run the repository verification gate and record its result below.

## Evidence Log

| Date | Milestone | Evidence |
| --- | --- | --- |
| 2026-09-21 | S0 | `.venv/bin/python -m pytest -q tests/unit/test_coordinator.py tests/unit/test_re_controller.py tests/unit/test_re_lifecycle.py tests/unit/test_re_v2_controller.py` — 274 passed in 24.32s. |
| 2026-09-21 | S1 | Activated. Execution is already fail-closed through `src/codegen/retirement.py`; deletion inventory is next. |

## Drift Guard

Until S7 is complete:

- Do not add another RE protocol generation.
- Do not add a third CLI dispatch layer.
- Do not add new behavior to a path scheduled for deletion.
- Do not create a general framework before two active consumers need it.
- Do not mark a milestone done without recording its verification evidence.

