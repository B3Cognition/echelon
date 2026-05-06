# Phase: phase1-why1
# Source: echelon.run.md §3 — WHY1 Phase (Assumption Challenge)
# Agent: SAGE (mode: WHY1)
# Read by: COMMANDER before dispatching SAGE WHY1

## 3. WHY1 Phase (Assumption Challenge — UNDERSTAND)

> **Note:** Still in UNDERSTAND phase. Outputs go to staging area.

### Context Pack Assembly

Read and include in the subagent prompt (all from `.specify/squad/staging/`):

- `glossary.md` + `mental-model.md` + `boundaries.md`
- `assumptions.md` + `unknowns.md`
- `calibration-profile.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, calibration-profile.yaml, reasoning-journal.json — all from .specify/squad/staging/]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **assumption-challenge mode** (WHY1 — pre-WHAT).
  Do NOT run Understanding metrics (no specs exist yet). Challenge assumptions for logical consistency, identify contradictions in the domain map, perform pre-mortem analysis, flag unknowns needing INVESTIGATOR investigation. Produce outputs in `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "SAGE (WHY1): assumption challenge and pre-mortem analysis"

### Expected Outputs

- `assumption-review.md`
- Updated `unknowns.md` (if new unknowns discovered)
- `issues.md` (if critical issues found)

### Gate Check

Read WHY1 outputs:

- If **CRITICAL** issues found in `assumption-review.md` → route back to DISCOVER (re-investigate). Increment iteration counter. Check iteration limit.
- If **PASS** (no critical issues, all major assumptions validated or flagged) → proceed to WHAT.

**Transition:** `phases[phase1-constitution]` — see `workflow/definition.yaml`
