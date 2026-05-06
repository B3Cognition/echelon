# Phase: phase3-plan
# Source: echelon.run.md §10 — PLAN Phase (Task Breakdown)
# Agent: ORCHESTRATOR
# Read by: COMMANDER before dispatching ORCHESTRATOR

## 10. PLAN Phase (Task Breakdown)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `research.md` + `data-model.md`
- `contracts/` + `test-strategy.md`
- Risk data from specialists (threat-model.md, performance-requirements.md, etc.)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include plan.md, research.md, data-model.md, contracts/, test-strategy.md, risk data from specialists, reasoning-journal.json]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol.
  Break the architecture into executable tasks (foundation, features, polish). Identify the critical path. Map task dependencies and parallelization. Assess risk per task. Include test tasks from test-strategy.md. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "ORCHESTRATOR: task breakdown, critical path, dependencies, risk"

### Expected Outputs

- `tasks.md`
- `critical-path.md`
- `risk-matrix.md`
- `dependencies.md`

Before this transition, COMMANDER performs phase-boundary timing writes in order:

1. Close `phase3-solution` with `scripts/bash/phase-timing.sh end_phase phase3-solution`.
2. Open `phase4-build` with `scripts/bash/phase-timing.sh start_phase phase4-build 7200`.
3. Confirm updated `phase_timings` are flushed to `state.json` before consensus dispatch.

**Transition:** `phases[phase3-consensus]` — see `workflow/definition.yaml`
