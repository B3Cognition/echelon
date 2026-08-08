# Phase: phase2-tracker-alignment
# Source: echelon.run.md §6c — echelon.tracker (TRACKER) Intent Alignment Check
# Agent: echelon.tracker (TRACKER) (mode: alignment-check)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.tracker (TRACKER) for alignment check

### 6c. echelon.tracker (TRACKER) — Intent Alignment Check

After echelon.gatekeeper (GATEKEEPER) passes, dispatch echelon.tracker (TRACKER) to verify intent alignment:

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include user-intent.md, feasibility.md, mvp-scope.md, extension/templates/intent-alignment-check-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **alignment-check mode**.
  Read `user-intent.md` and echelon.gatekeeper (GATEKEEPER)'s outputs (`feasibility.md`, `mvp-scope.md`). Check whether echelon.gatekeeper (GATEKEEPER)'s scoping decisions align with the user's stated intent. If MISALIGNED, emit an alignment alert with specific divergence points. Produce `intent-alignment-check.md` in `{spec_dir}/` using the provided template. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon.tracker (TRACKER): verify echelon.gatekeeper (GATEKEEPER) scope aligns with user intent"

If echelon.tracker (TRACKER) reports MISALIGNED:
- MANAGER prints the divergence to terminal
- In `guided` or `semi` mode: pause for human confirmation
- In `banzai` mode: log the divergence, proceed with echelon.gatekeeper (GATEKEEPER)'s scope

### Routing Verdict Contract — MANDATORY

TRACKER must emit one of these canonical `echelon_result.verdict` values:

- `ALIGNED` — scope still matches user intent; continue.
- `DRIFT` — scope drift was detected and recorded, but progress may continue under the current mode.
- `STOP_AND_ASK` — user input is required before continuing.

Every question-bearing result must use `STOP_AND_ASK`; never attach a question
to `ESCALATE` or another verdict. Use this exact controller input shape:

```yaml
echelon_result:
  verdict: STOP_AND_ASK
  state_updates:
    status: blocked
    blocked_reason: human_clarification_required
    escalation_question: "<one concrete alignment decision>"
    escalation_recommended_answer: "<evidence-backed recommendation>"
    escalation_risk_level: "<low | medium | high | critical>"
```

Include `escalation_recommended_answer` and `escalation_risk_level` together
only when evidence supports a recommendation; otherwise omit both. The
controller owns decision persistence, clarification writes, and state cleanup.

### Output Filename — MANDATORY

Always name the output file exactly `intent-alignment-check.md`. **NEVER** produce `alignment-report.md`, `alignment.md`, `tracker-alignment.md`, or any other variant — downstream phases (and any future automated checks) look up this file by exact name.

The harness verifies the exact output path and validates the artifact after
dispatch. Do not run a shell check or rediscover the spec directory.

**Transition:** `phases[phase3-specialists]` — see `workflow/definition.yaml`

### Intent Alignment Structural Gate

TRACKER authors and repairs `intent-alignment-check.md`. Projectable verdicts
continue through the provider-free `phase2-intent-alignment-structural` node,
which writes `intent-alignment-check-structural-report.json` and owns pass,
findings, attempt, and exhaustion state.

On re-dispatch, the prompt contains the report path and repair instructions.
Repair every listed finding, preserve passing sections, and return the normal
alignment verdict. Deterministic validation and structural gate state remain
harness-owned. `STOP_AND_ASK` blocks at TRACKER before certification. TRACKER
must not emit `intent_alignment_verdict` or structural state. A manual
structural run without a persisted verdict recovers by resuming
`phase2-tracker-alignment`.
