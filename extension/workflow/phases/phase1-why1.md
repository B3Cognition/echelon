# Phase: phase1-why1
# Source: echelon.run.md §3 — WHY1 Phase (Assumption Challenge)
# Agent: speckit-echelon-sage (SAGE) (mode: WHY1)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-sage (SAGE) WHY1

## 3. WHY1 Phase (Assumption Challenge — UNDERSTAND)

> **Note:** Still in UNDERSTAND phase. Outputs go to staging area.

### Context Pack Assembly

Read and include in the subagent prompt:

| File | Path |
|------|------|
| `glossary.md` | `.specify/squad/staging/glossary.md` |
| `mental-model.md` | `.specify/squad/staging/mental-model.md` |
| `boundaries.md` | `.specify/squad/staging/boundaries.md` |
| `assumptions.md` | `.specify/squad/staging/assumptions.md` |
| `unknowns.md` | `.specify/squad/staging/unknowns.md` |
| `calibration_map entry for SAGE` | Built by COMMANDER at init from `knowledge-base/calibration-profile.yaml`. Mark `[ABSENT]` on cold start — COMMANDER injects it via the Pre-Dispatch Calibration Injection protocol. |
| `reasoning-journal.json` | `.specify/squad/staging/reasoning-journal.json` |

**MANDATORY — verify each file before dispatch.** If a file is absent, include it in the prompt as `[ABSENT: <path>]` rather than silently omitting it. SAGE must know what's missing so it can flag related assumptions accordingly. The calibration_map entry is commonly absent on cold start — that is acceptable; mark it `[ABSENT]`.

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reasoning-journal.json from .specify/squad/staging/; calibration_map entry for SAGE from COMMANDER init (mark [ABSENT] if cold start)]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **assumption-challenge mode** (WHY1 — pre-WHAT).
  Do NOT run Understanding metrics (no specs exist yet). Challenge assumptions for logical consistency, identify contradictions in the domain map, perform pre-mortem analysis, flag unknowns needing speckit-echelon-investigator (INVESTIGATOR) investigation. Produce outputs in `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-sage (SAGE) (WHY1): assumption challenge and pre-mortem analysis"

### Expected Outputs

- `assumption-review.md`
- Updated `unknowns.md` (if new unknowns discovered)
- `issues.md` (if critical issues found)

### Gate Check

Read WHY1 outputs:

- If **CRITICAL** issues found in `assumption-review.md` → route back to DISCOVER (re-investigate). Increment iteration counter. Check iteration limit.
- If **PASS** (no critical issues, all major assumptions validated or flagged) → proceed to WHAT.

**Transition:** `phases[phase1-constitution]` — see `workflow/definition.yaml`
