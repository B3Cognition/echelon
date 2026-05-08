# Phase: phase3-sentinel
# Source: echelon.run.md §9 — TEST speckit-echelon-architect (ARCHITECT) Phase
# Agent: speckit-echelon-sentinel (SENTINEL)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-sentinel (SENTINEL)

## 9. TEST speckit-echelon-architect (ARCHITECT) Phase (Mandatory)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `data-model.md`
- `spec.md` (acceptance criteria)
- `contracts/`
- `quality-gates.md` — specifically the "Testability Sub-Metrics" section (hard_constraint_ratio, constraint_density, negative_space_coverage) for testability-informed test strategy
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include plan.md, data-model.md, spec.md, contracts/, quality-gates.md, reasoning-journal.json]
  </context>

  <instructions>
  You are SENTINEL. Read agents/solution/sentinel.md for your complete protocol.
  Produce a comprehensive test strategy from plan.md + data-model.md + spec.md acceptance criteria. Use the testability sub-metrics from quality-gates.md (hard_constraint_ratio, constraint_density, negative_space_coverage) to identify which testability dimension is weakest and prioritize test effort accordingly. Map every acceptance criterion to a test approach. Define the test pyramid. Identify boundary value cases. If acceptance criteria have no testable form, flag them for routing back to speckit-echelon-cartographer (CARTOGRAPHER). Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-sentinel (SENTINEL): testability-informed test strategy and coverage mapping"

### Expected Outputs

- `test-strategy.md`
- `test-architecture.md`
- `coverage-map.md`

### Gate Check

If TEST speckit-echelon-architect (ARCHITECT) flags untestable acceptance criteria → route back to WHAT for amendment. Increment iteration. Check limits.

Before this transition, speckit-echelon-commander (COMMANDER) updates timing state via `scripts/bash/phase-timing.sh`:

1. Keep `phase3-solution` open (intra-phase transition: `test-architect` -> `plan`).
2. If missing from recovered state, initialize `phase3-solution` using `start_phase phase3-solution 2400` before dispatching PLAN.
3. Persist `state.json` timing updates before dispatch.

**Transition:** `phases[phase3-plan]` — see `workflow/definition.yaml`
