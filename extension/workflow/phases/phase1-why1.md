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
| `glossary.md` | `${STAGING_DIR}/glossary.md` |
| `mental-model.md` | `${STAGING_DIR}/mental-model.md` |
| `boundaries.md` | `${STAGING_DIR}/boundaries.md` |
| `assumptions.md` | `${STAGING_DIR}/assumptions.md` |
| `unknowns.md` | `${STAGING_DIR}/unknowns.md` |
| `calibration_map entry for speckit-echelon-sage (SAGE)` | Built by speckit-echelon-commander (COMMANDER) at init from `knowledge-base/calibration-profile.yaml`. Mark `[ABSENT]` on cold start — speckit-echelon-commander (COMMANDER) injects it via the Pre-Dispatch Calibration Injection protocol. |
| `reasoning-journal.jsonl` | `${SQUAD_DIR}/reasoning-journal.jsonl` |

**MANDATORY — verify each file before dispatch.** If a file is absent, include it in the prompt as `[ABSENT: <path>]` rather than silently omitting it. speckit-echelon-sage (SAGE) must know what's missing so it can flag related assumptions accordingly. The calibration_map entry is commonly absent on cold start — that is acceptable; mark it `[ABSENT]`.

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reasoning-journal.jsonl from ${STAGING_DIR}/; calibration_map entry for speckit-echelon-sage (SAGE) from speckit-echelon-commander (COMMANDER) init (mark [ABSENT] if cold start)]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **assumption-challenge mode** (WHY1 — pre-WHAT).
  Always challenge assumptions for logical consistency, identify contradictions in the domain map, perform pre-mortem analysis, and flag unknowns needing speckit-echelon-investigator (INVESTIGATOR) investigation. Do NOT run Understanding metrics (no specs exist yet). Produce outputs in `${STAGING_DIR}/`. Append entries to `reasoning-journal.jsonl`.
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

### User-gated CRITICAL issues

When CRITICAL issues are **user-gated** — they require information only the user holds
(legal rights, product positioning decisions, audience policy, cost envelope) and cannot
be resolved by any squad agent — include in `echelon_result.state_updates`:

```yaml
escalation_question: |
  Q1: <compact blocking question — one line, state the stakes>
  Q2: <compact blocking question>
blocked_reason: |
  WHY1: CRITICAL user-gated issues — squad-internal iteration cannot substitute for user input
```

**Criteria — ALL must be true to set escalation_question:**

1. Cannot be resolved by any squad agent (DISCOVER, SYNTHESIZER, MODELER, TRACKER, INVESTIGATOR)
2. Requires information only the user holds (legal rights, positioning decisions, audience policy)
3. Proceeding without it requires an arbitrary coin-flip that binds all downstream phases

**Always route squad-solvable CRITICAL issues back to DISCOVER. Do NOT set escalation_question for them** (missing boundaries,
glossary gaps, unread manual pages, contradictions resolvable by ORACLE/INVESTIGATOR).
Those keep routing to DISCOVER as normal.

The harness reads `escalation_question` and either:

- **banzai mode** → dispatches COMMANDER for best-judgment answers, run continues
- **semi/guided mode** → stops the run; user answers via `echelon resume "<answers>"`
