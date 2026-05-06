# Phase: phase2-decide
# Source: echelon.run.md §6 — ASSESS Phase (Kill Gate)
# Agent: GATEKEEPER
# Read by: COMMANDER before dispatching GATEKEEPER

## 6. ASSESS Phase (Kill Gate)

### Context Pack Assembly

Read and include in the subagent prompt:

- `spec.md` + `glossary.md` + `assumptions.md`
- `issues.md` (from WHY2)
- `calibration-profile.yaml` + `estimates-log.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include spec.md, glossary.md, assumptions.md, issues.md from WHY2, calibration-profile.yaml, estimates-log.yaml, reasoning-journal.json]
  </context>

  <instructions>
  You are GATEKEEPER. Read agents/feasibility/gatekeeper.md for your complete protocol.
  Evaluate feasibility (can this be built within constraints?). Estimate effort using Function Point Analysis adjusted by calibration data. Prioritize features with Kano + RICE. Scope MVP. **Kill gate:** if unfeasible or all low-priority, produce a kill report using `templates/kill-report.md`. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "GATEKEEPER: feasibility, estimation, prioritization, kill gate"

### Expected Outputs

- `feasibility.md`
- `prioritization.md`
- `estimates.md`
- `mvp-scope.md`

### Gate Check

Read ASSESS outputs:

- **KILL** verdict → write kill report to `specs/{feature}/kill-report.md`, set state.json status to "killed", print summary, STOP.
- **DEFER** verdict → reduce scope, re-route to WHAT. Track DEFER count. **DEFER loop >= 2 with no scope stabilization → kill or escalate to human.**
- **PASS** → proceed to specialist summoning.

Before this transition, COMMANDER updates timing state via `scripts/bash/phase-timing.sh`:

1. Ensure `phase2-decide` timing is active (budget `1800` seconds) by calling `start_phase phase2-decide 1800` before the first phase2 dispatch (`WHAT`) if no `start_ts` exists.
2. For intra-phase transition (`assess` -> `strategic_overview`), do not close the phase timing window yet.
3. Persist `state.json` after timing update before dispatching the next agent.

Phase budget map for consistency across all transitions:

- `phase1-understand=2400`
- `phase2-decide=1800`
- `phase3-solution=2400`
- `phase4-build=7200`

**Transition:** `phases[phase2-strategic-overview]` — see `workflow/definition.yaml`
