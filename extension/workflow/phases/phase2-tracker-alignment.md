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
  [include user-intent.md, feasibility.md, mvp-scope.md, extension/templates/intent-alignment-check-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **alignment-check mode**.
  Read `user-intent.md` and speckit-echelon-gatekeeper (GATEKEEPER)'s outputs (`feasibility.md`, `mvp-scope.md`). Check whether speckit-echelon-gatekeeper (GATEKEEPER)'s scoping decisions align with the user's stated intent. If MISALIGNED, emit an alignment alert with specific divergence points. Produce `intent-alignment-check.md` in `{spec_dir}/` using the provided template. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-tracker (TRACKER): verify speckit-echelon-gatekeeper (GATEKEEPER) scope aligns with user intent"

If speckit-echelon-tracker (TRACKER) reports MISALIGNED:
- MANAGER prints the divergence to terminal
- In `guided` or `semi` mode: pause for human confirmation
- In `banzai` mode: log the divergence, proceed with speckit-echelon-gatekeeper (GATEKEEPER)'s scope

### Output Filename — MANDATORY

Always name the output file exactly `intent-alignment-check.md`. **NEVER** produce `alignment-report.md`, `alignment.md`, `tracker-alignment.md`, or any other variant — downstream phases (and any future automated checks) look up this file by exact name.

Verification before transitioning to phase3-specialists:

```bash
[ -f "specs/${SPEC_DIR}/intent-alignment-check.md" ] || { echo "ERROR: intent-alignment-check.md missing" >&2; exit 1; }
```

**Transition:** `phases[phase3-specialists]` — see `workflow/definition.yaml`
