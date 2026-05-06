# Phase: phase2-tracker-alignment
# Source: echelon.run.md §6c — TRACKER Intent Alignment Check
# Agent: TRACKER (mode: alignment-check)
# Read by: COMMANDER before dispatching TRACKER for alignment check

### 6c. TRACKER — Intent Alignment Check

After GATEKEEPER passes, dispatch TRACKER to verify intent alignment:

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include user-intent.md, feasibility.md, mvp-scope.md, reasoning-journal.json]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **alignment-check mode**.
  Read `user-intent.md` and GATEKEEPER's outputs (`feasibility.md`, `mvp-scope.md`). Check whether GATEKEEPER's scoping decisions align with the user's stated intent. If MISALIGNED, emit an alignment alert with specific divergence points. Produce `intent-alignment-check.md` in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "TRACKER: verify GATEKEEPER scope aligns with user intent"

If TRACKER reports MISALIGNED:
- MANAGER prints the divergence to terminal
- In `guided` or `semi` mode: pause for human confirmation
- In `banzai` mode: log the divergence, proceed with GATEKEEPER's scope

**Transition:** `phases[phase3-specialists]` — see `workflow/definition.yaml`
