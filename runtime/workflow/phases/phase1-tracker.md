# Phase: phase1-tracker
# Source: echelon.run.md §2c — echelon.tracker (TRACKER) Intent Model Capture
# Agent: echelon.tracker (TRACKER)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.tracker (TRACKER)

## 2c. echelon.tracker (TRACKER) — Intent Model Capture

> **Note:** echelon.tracker (TRACKER) captures the user's stated intent before requirements formalization. This produces `user-intent.md` which echelon.gatekeeper (GATEKEEPER) needs to honor rule #3 ("ALWAYS preserve user intent; NEVER override user intent").

### Context Pack Assembly

Read and include in the subagent prompt:

- User input (the original request)
- ALL DISCOVER outputs (from `${STAGING_DIR}/`)
- `extension/templates/user-intent-template.md`
- `extension/templates/stakeholder-model-template.md`
- `reasoning-journal.jsonl`

### Dispatch

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include user input (the original request), all DISCOVER outputs from ${STAGING_DIR}/, tracker intent templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol.
  Read the user's original request and echelon.scout (SCOUT)'s discovery outputs. Capture the user's stated intent, scope preferences, and explicit constraints into `user-intent.md` using the provided template. Produce `stakeholder-model.md` when multiple stakeholders are detectable. Produce outputs in `${STAGING_DIR}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon.tracker (TRACKER): capture user intent model before requirements formalization"

### Expected Outputs

- `user-intent.md` (in staging, later moved to spec directory)
- `stakeholder-model.md` (if multiple stakeholders are detectable)

### Routing Verdict Contract — MANDATORY

TRACKER must emit one of these canonical `echelon_result.verdict` values:

- `ALIGNED` — intent is clear enough to continue to assumption challenge.
- `DRIFT` — intent risks were recorded, but progress may continue.
- `STOP_AND_ASK` — user input is required before continuing.

Every question-bearing result must use `STOP_AND_ASK`; never attach a question
to `ESCALATE` or another verdict. Use this exact controller input shape:

```yaml
echelon_result:
  verdict: STOP_AND_ASK
  state_updates:
    status: blocked
    blocked_reason: human_clarification_required
    escalation_question: "<one concrete question>"
    escalation_recommended_answer: "<evidence-backed recommendation>"
    escalation_risk_level: "<low | medium | high | critical>"
```

Include `escalation_recommended_answer` and `escalation_risk_level` together
only when evidence supports a recommendation; otherwise omit both. The
controller owns decision persistence, clarification writes, and state cleanup.

**Transition:** `phases[phase1-why1]` — see `workflow/definition.yaml`
