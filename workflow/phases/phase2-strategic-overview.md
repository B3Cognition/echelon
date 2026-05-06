# Phase: phase2-strategic-overview
# Source: echelon.run.md §6b — STRATEGIC OVERVIEW (Risk Map)
# Agent: STRATEGIST
# Read by: COMMANDER before dispatching STRATEGIST

### 6b. STRATEGIC OVERVIEW (Risk Map)

After ASSESS passes, dispatch STRATEGIC OVERVIEW to build the initial risk-weighted map:

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, feasibility.md, estimates.md, prioritization.md, unknowns.md]
  </context>

  <instructions>
  You are STRATEGIST. Read agents/control/strategist.md for your complete protocol.
  Build a risk-weighted strategic map of the project. Identify which components carry the highest business + technical risk. Flag where effort allocation should be concentrated.
  Produce `strategic-overview.md` in `.specify/specs/{NNN}-{feature}/`.
  </instructions>
  ```

- **description:** "STRATEGIC OVERVIEW: risk-weighted project map"

Read the strategic overview. Use it to prioritize specialist allocation: spend INVESTIGATOR time on high-blast-radius decisions, not low-risk areas.

Before this transition, COMMANDER updates timing state via `scripts/bash/phase-timing.sh`:

1. Keep `phase2-decide` open (this is still an intra-phase transition: `strategic_overview` -> `specialists`).
2. If `phase2-decide` was never started due to restart recovery, initialize with `start_phase phase2-decide 1800` before continuing.
3. Persist `state.json` after timing reconciliation and before dispatching specialists.

**Transition:** `phases[phase2-tracker-alignment]` — see `workflow/definition.yaml`
