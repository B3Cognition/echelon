# Phase: phase1-tracker
# Source: echelon.run.md §2c — TRACKER Intent Model Capture
# Agent: TRACKER
# Read by: COMMANDER before dispatching TRACKER

## 2c. TRACKER — Intent Model Capture

> **Note:** TRACKER captures the user's stated intent before requirements formalization. This produces `user-intent.md` which GATEKEEPER needs to honor NEVER rule #3 ("NEVER override user intent").

### Context Pack Assembly

Read and include in the subagent prompt:

- User input (the original request)
- ALL DISCOVER outputs (from `.specify/squad/staging/`)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include user input (the original request), all DISCOVER outputs from .specify/squad/staging/, reasoning-journal.json]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol.
  Read the user's original request and SCOUT's discovery outputs. Capture the user's stated intent, scope preferences, and explicit constraints into `user-intent.md`. Produce outputs in `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "TRACKER: capture user intent model before requirements formalization"

### Expected Outputs

- `user-intent.md` (in staging, later moved to spec directory)

**Transition:** `phases[phase1-why1]` — see `workflow/definition.yaml`
