# Phase: build-7-integration
# Source: echelon.build.md §7 — Phase Checkpoint (INTEGRATION)
# Agents: speckit-echelon-integrator (INTEGRATOR), then optionally speckit-echelon-visual-validator (VISUAL speckit-echelon-validator (VALIDATOR))
# Read by: speckit-echelon-commander (COMMANDER) after all tasks in a phase group complete

## 7. Phase Checkpoint (INTEGRATION)

### When

After all tasks in a phase group (e.g., "Foundation") are complete, run the speckit-echelon-integrator (INTEGRATOR) before proceeding to the next phase group.

### 7.1 Dispatch speckit-echelon-integrator (INTEGRATOR)

Compile context pack:

- All code produced in this phase group
- Build configuration files
- `contracts/`
- `data-model.md`
- Prior integration reports (if any)

Use the Agent tool:

- **subagent_type:** `speckit-echelon-integrator`
- **prompt:**

  ```xml
  <context>
  [include files listed above]
  </context>

  <instructions>
  You are INTEGRATOR. Read agents/build/integrator.md for your complete protocol.
  Verify system integration after phase "{phase_group}".
  Write `integration-report.md`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-integrator (INTEGRATOR): phase '{phase_group}' — system integration check"

### 7.2 Handle Result

- **PASS** — Run `endocrine.sh on_gate_pass speckit-echelon-integrator (INTEGRATOR)`. Run 7.2.1 (browser-app visual check if applicable). Record checkpoint. Proceed to next phase group.
- **FAIL** — Run `endocrine.sh on_gate_fail speckit-echelon-integrator (INTEGRATOR)` + `endocrine.sh on_low_confidence speckit-echelon-implementer (IMPLEMENTER)` (for responsible task). Route integration failures back to the responsible task's speckit-echelon-implementer (IMPLEMENTER). Re-run speckit-echelon-integrator (INTEGRATOR) after fixes. Max 2 fix cycles per phase checkpoint. If still failing, flag phase as DEGRADED and proceed.

### 7.2.1 Visual Validator Dispatch (MANDATORY for browser/SPA apps)

**Detect stack:** Check `research.md` and `plan.md` for browser/SPA indicators: Vite, React, Vue, Svelte, Angular, SolidJS, Astro, Next.js, Nuxt, Remix, static site, or any spec requirement for a web UI.

**If browser/SPA detected:** Dispatch speckit-echelon-visual-validator (VISUAL speckit-echelon-validator (VALIDATOR)) immediately after speckit-echelon-integrator (INTEGRATOR) PASS — before recording the checkpoint and before proceeding to the next phase group.

Use the Agent tool:

- **subagent_type:** `speckit-echelon-visual-validator`
- **prompt:**

  ```xml
  <context>
  [include spec.md, plan.md, code from this phase]
  </context>

  <instructions>
  You are VISUAL VALIDATOR. Read agents/build/visual-validator.md for your complete protocol.
  Verify that the browser application renders correctly after phase "{phase_group}". Build the app, serve it, use Playwright to screenshot every page/view, and verify nothing is blank.
  Write or append to `visual-validation-report.md`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-visual-validator (VISUAL speckit-echelon-validator (VALIDATOR)): phase '{phase_group}' — browser render check"

Handle result:

- **VISUAL_PASS** — proceed to 7.3.
- **VISUAL_FAIL** — Run `endocrine.sh on_gate_fail speckit-echelon-implementer (IMPLEMENTER)`. Route visual failures back to speckit-echelon-implementer (IMPLEMENTER) with the specific rendering issues (blank page, missing components, console errors). speckit-echelon-implementer (IMPLEMENTER) fixes, speckit-echelon-integrator (INTEGRATOR) re-runs, then speckit-echelon-visual-validator (VISUAL speckit-echelon-validator (VALIDATOR)) re-runs. Max 2 fix cycles. If still failing, flag phase as DEGRADED and escalate to human.

**If not browser/SPA:** skip 7.2.1 and proceed directly to 7.3.

### 7.3 Record Checkpoint

Return the full updated `build` object in `echelon_result.state_updates`, appending this checkpoint to `build.phase_checkpoints` because harness state updates are shallow top-level merges:

```yaml
build:
  phase_checkpoints:
    - phase_group: "{name}"
      status: "PASS"
      tasks_completed: "{count}"
      integration_issues: 0
      timestamp: "{ISO-8601}"
```
