# Phase: phase2-decide
# Source: echelon.run.md §6 — ASSESS Phase (Kill Gate)
# Agent: echelon.gatekeeper (GATEKEEPER)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.gatekeeper (GATEKEEPER)

## 6. ASSESS Phase (Kill Gate)

### Context Pack Assembly — MUST INCLUDE

Every file below MUST be included (or marked `[ABSENT: <path>]` if missing). Silently omitting any of these is a routing error — echelon.gatekeeper (GATEKEEPER) calibrates against the calibration profile, scopes against the glossary, and re-uses prior estimates if available.

| File | Path | Notes |
| --- | --- | --- |
| `spec.md` | `{spec_dir}/spec.md` | Required |
| `glossary.md` | `{spec_dir}/glossary.md` (or `${STAGING_DIR}/glossary.md` if not yet moved) | Required |
| `requirements-overview.md` | `{spec_dir}/requirements-overview.md` | Required — Phase 1 orientation, not final delivery overview |
| `assumptions.md` | `{spec_dir}/assumptions.md` (or staging) | Required |
| `issues.md` | `{spec_dir}/issues.md` | From WHY2 |
| `calibration-profile.yaml` | `knowledge-base/calibration-profile.yaml` | Mark `[ABSENT]` on cold start |
| `estimates-log.yaml` | `knowledge-base/estimates-log.yaml` | Mark `[ABSENT]` on cold start |
| `.echelon/runtime/templates/feasibility-template.md` | `.echelon/runtime/templates/feasibility-template.md` | Required |
| `.echelon/runtime/templates/prioritization-template.md` | `.echelon/runtime/templates/prioritization-template.md` | Required |
| `.echelon/runtime/templates/estimates-template.md` | `.echelon/runtime/templates/estimates-template.md` | Required |
| `.echelon/runtime/templates/mvp-scope-template.md` | `.echelon/runtime/templates/mvp-scope-template.md` | Required |
| `.echelon/runtime/templates/kill-report.md` | `.echelon/runtime/templates/kill-report.md` | Required |
| `reasoning-journal.jsonl` | `${SQUAD_DIR}/reasoning-journal.jsonl` | Required |

The harness assembles the declared context pack before dispatch. Treat absent
calibration files as a cold start; do not search the filesystem or run a
preflight command to rediscover context.

### Dispatch

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include spec.md, glossary.md, assumptions.md, issues.md from WHY2, calibration-profile.yaml, estimates-log.yaml, gatekeeper first-pass templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are GATEKEEPER. Read subagents/echelon.gatekeeper.md for your complete protocol.
  Evaluate feasibility (can this be built within constraints?). Estimate effort using Function Point Analysis adjusted by calibration data. `estimates.md` must include Phase A specification authoring and Phase B implementation, each as human-only and AI-assisted scenarios. The AI-assisted scenario must include Phase A, Phase B, and total token and USD budgets with a documented pricing basis. Prioritize features with Kano + RICE. Scope MVP. **Kill gate:** if unfeasible or all low-priority, produce a kill report using `.echelon/runtime/templates/kill-report.md`. Produce outputs in `{spec_dir}/` using the provided templates. If any output already exists from a prior interrupted attempt, read it before updating it; never create backup, temporary, alternate, or shell-written files to bypass write guards. Return the gate decision as the top-level `echelon_result.verdict` only (`PASS`, `KILL`, or `DEFER`); do not return `gate_decision` or `phase_recommendation` in `state_updates` for this first-pass phase. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon.gatekeeper (GATEKEEPER): feasibility, estimation, prioritization, kill gate"

### Expected Outputs

- `feasibility.md`
- `prioritization.md`
- `estimates.md`
- `mvp-scope.md`

### Gate Check

Read ASSESS outputs:

- **KILL** verdict → write kill report to `{spec_dir}/kill-report.md`, return `status: killed` in `echelon_result.state_updates`, return a summary journal entry, STOP. The harness applies the state update and routes to `done`.
- **DEFER** verdict → reduce scope, re-route to WHAT. Track DEFER count. **DEFER loop >= 2 with no scope stabilization → kill or escalate to human.**
- **PASS** → proceed to specialist summoning.

For KILL, include this state update in the phase result:

```yaml
echelon_result:
  verdict: KILL
  state_updates:
    status: killed
```

The harness owns the `phase2-decide` timing window declared in
`workflow/definition.yaml`; the agent does not start or stop timers.

**Transition:** `phases[phase2-strategic-overview]` — see `workflow/definition.yaml`

### Feasibility Structural Gate

GATEKEEPER authors and repairs `feasibility.md`. After a projectable verdict,
the provider-free `phase2-feasibility-structural` node certifies it and writes
`feasibility-structural-report.json`. That visible node owns pass, findings,
attempt, and exhaustion state and applies `governance.max_repair_attempts` plus
`governance.on_exhausted`.

On re-dispatch, the prompt contains the report path and repair instructions.
Repair every listed finding, preserve passing sections, and return the normal
phase verdict. Deterministic validation and structural gate state remain
harness-owned. GATEKEEPER must not emit `feasibility_verdict` or any
`feasibility_structural_*` field. A manual structural run without a persisted
verdict blocks; resume `phase2-decide` to recover.
