# Phase: phase2-strategic-overview
# Source: echelon.run.md §6b — STRATEGIC OVERVIEW (Risk Map)
# Agent: speckit-echelon-strategist (STRATEGIST)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-strategist (STRATEGIST)

### 6b. STRATEGIC OVERVIEW (Risk Map)

After ASSESS passes, dispatch STRATEGIC OVERVIEW to build the initial risk-weighted map:

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, feasibility.md, estimates.md, prioritization.md, unknowns.md, extension/templates/strategic-overview-template.md]
  </context>

  <instructions>
  You are STRATEGIST. Read agents/control/strategist.md for your complete protocol.
  Build a risk-weighted strategic map of the project. Identify which components carry the highest business + technical risk. Flag where effort allocation should be concentrated.
  Produce `strategic-overview.md` in `specs/{NNN}-{feature}/` using the provided template.
  </instructions>
  ```

- **description:** "STRATEGIC OVERVIEW: risk-weighted project map"

Read the strategic overview. Use it to prioritize specialist allocation: spend speckit-echelon-investigator (INVESTIGATOR) time on high-blast-radius decisions, not low-risk areas.

**MANDATORY — run before transitioning to phase2-tracker-alignment:**

```bash
# Budget: definition.yaml phases[phase2-decide].budget_seconds = 1800
# Ensure phase2-decide window is open (idempotent — skips if already started)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase2-decide 1800
```

phase2-decide stays open through this phase — it closes in phase3-specialists.

**Transition:** `phases[phase2-tracker-alignment]` — see `workflow/definition.yaml`
