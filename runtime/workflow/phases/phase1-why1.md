# Phase: phase1-why1
# Source: echelon.run.md §3 — WHY1 Phase (Assumption Challenge)
# Agent: echelon.sage (SAGE) (mode: WHY1)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.sage (SAGE) WHY1

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
| `sage-assumption-review-template.md` | `agents/exploration/templates/sage-assumption-review-template.md` |
| `sage-issues-template.md` | `agents/exploration/templates/sage-issues-template.md` |
| `calibration_map entry for echelon.sage (SAGE)` | Built by echelon.commander (COMMANDER) at init from `knowledge-base/calibration-profile.yaml`. Mark `[ABSENT]` on cold start — echelon.commander (COMMANDER) injects it via the Pre-Dispatch Calibration Injection protocol. |
| `reasoning-journal.jsonl` | `${SQUAD_DIR}/reasoning-journal.jsonl` |

**MANDATORY — verify each file before dispatch.** If a file is absent, include it in the prompt as `[ABSENT: <path>]` rather than silently omitting it. echelon.sage (SAGE) must know what's missing so it can flag related assumptions accordingly. The calibration_map entry is commonly absent on cold start — that is acceptable; mark it `[ABSENT]`.

### Dispatch

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reasoning-journal.jsonl from ${STAGING_DIR}/; sage WHY1 output templates; calibration_map entry for echelon.sage (SAGE) from echelon.commander (COMMANDER) init (mark [ABSENT] if cold start)]
  </context>

  <instructions>
  You are SAGE. Read subagents/echelon.sage.md for your complete protocol. Operate in **assumption-challenge mode** (WHY1 — pre-WHAT).
  Always challenge assumptions for logical consistency, identify contradictions in the domain map, perform pre-mortem analysis, and flag unknowns needing echelon.investigator (INVESTIGATOR) investigation. Do NOT run Understanding metrics (no specs exist yet). Produce outputs in `${STAGING_DIR}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon.sage (SAGE) (WHY1): assumption challenge and pre-mortem analysis"

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
be resolved by any squad agent — return this controller input:

```yaml
echelon_result:
  verdict: STOP_AND_ASK
  state_updates:
    status: blocked
    blocked_reason: human_clarification_required
    escalation_question: "<compact blocking question; state the stakes>"
    escalation_recommended_answer: "<evidence-backed recommendation>"
    escalation_risk_level: "<low | medium | high | critical>"
```

**Criteria — ALL must be true to set escalation_question:**

1. Cannot be resolved by any squad agent (DISCOVER, SYNTHESIZER, MODELER, TRACKER, INVESTIGATOR)
2. Requires information only the user holds (legal rights, positioning decisions, audience policy)
3. Proceeding without it requires an arbitrary coin-flip that binds all downstream phases

**Always route squad-solvable CRITICAL issues back to DISCOVER. Do NOT set escalation_question for them** (missing boundaries,
glossary gaps, unread manual pages, contradictions resolvable by ORACLE/INVESTIGATOR).
Those keep routing to DISCOVER as normal.

Include `escalation_recommended_answer` and `escalation_risk_level` together
only when evidence supports a recommendation; otherwise omit both. Never use a
question-bearing verdict other than `STOP_AND_ASK`. The controller owns
autonomy routing, clarification writes, and state cleanup.
