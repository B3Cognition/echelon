# Phase: phase1-tracker
# Source: echelon.run.md §2c — speckit-echelon-tracker (TRACKER) Intent Model Capture
# Agent: speckit-echelon-tracker (TRACKER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-tracker (TRACKER)

## 2c. speckit-echelon-tracker (TRACKER) — Intent Model Capture

> **Note:** speckit-echelon-tracker (TRACKER) captures the user's stated intent before requirements formalization. This produces `user-intent.md` which speckit-echelon-gatekeeper (GATEKEEPER) needs to honor rule #3 ("ALWAYS preserve user intent; NEVER override user intent").

### Context Pack Assembly

Read and include in the subagent prompt:

- User input (the original request)
- ALL DISCOVER outputs (from `${STAGING_DIR}/`)
- `extension/templates/user-intent-template.md`
- `extension/templates/stakeholder-model-template.md`
- `reasoning-journal.jsonl`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include user input (the original request), all DISCOVER outputs from ${STAGING_DIR}/, tracker intent templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol.
  Read the user's original request and speckit-echelon-scout (SCOUT)'s discovery outputs. Capture the user's stated intent, scope preferences, and explicit constraints into `user-intent.md` using the provided template. Produce `stakeholder-model.md` when multiple stakeholders are detectable. Produce outputs in `${STAGING_DIR}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-tracker (TRACKER): capture user intent model before requirements formalization"

### Expected Outputs

- `user-intent.md` (in staging, later moved to spec directory)

**Transition:** `phases[phase1-why1]` — see `workflow/definition.yaml`
