# Phase: phase2-tracker-alignment
# Source: echelon.run.md §6c — speckit-echelon-tracker (TRACKER) Intent Alignment Check
# Agent: speckit-echelon-tracker (TRACKER) (mode: alignment-check)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-tracker (TRACKER) for alignment check

### 6c. speckit-echelon-tracker (TRACKER) — Intent Alignment Check

After speckit-echelon-gatekeeper (GATEKEEPER) passes, dispatch speckit-echelon-tracker (TRACKER) to verify intent alignment:

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include user-intent.md, feasibility.md, mvp-scope.md, reasoning-journal.json]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **alignment-check mode**.
  Read `user-intent.md` and speckit-echelon-gatekeeper (GATEKEEPER)'s outputs (`feasibility.md`, `mvp-scope.md`). Check whether speckit-echelon-gatekeeper (GATEKEEPER)'s scoping decisions align with the user's stated intent. If MISALIGNED, emit an alignment alert with specific divergence points. Produce `intent-alignment-check.md` in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-tracker (TRACKER): verify speckit-echelon-gatekeeper (GATEKEEPER) scope aligns with user intent"

If speckit-echelon-tracker (TRACKER) reports MISALIGNED:
- MANAGER prints the divergence to terminal
- In `guided` or `semi` mode: pause for human confirmation
- In `banzai` mode: log the divergence, proceed with speckit-echelon-gatekeeper (GATEKEEPER)'s scope

**Transition:** `phases[phase3-specialists]` — see `workflow/definition.yaml`
