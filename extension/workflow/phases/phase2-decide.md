# Phase: phase2-decide
# Source: echelon.run.md §6 — ASSESS Phase (Kill Gate)
# Agent: speckit-echelon-gatekeeper (GATEKEEPER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-gatekeeper (GATEKEEPER)

## 6. ASSESS Phase (Kill Gate)

### Context Pack Assembly — MUST INCLUDE

Every file below MUST be included (or marked `[ABSENT: <path>]` if missing). Silently omitting any of these is a routing error — speckit-echelon-gatekeeper (GATEKEEPER) calibrates against the calibration profile, scopes against the glossary, and re-uses prior estimates if available.

| File | Path | Notes |
| --- | --- | --- |
| `spec.md` | `specs/{NNN}-{feature}/spec.md` | Required |
| `glossary.md` | `specs/{NNN}-{feature}/glossary.md` (or `.specify/squad/staging/glossary.md` if not yet moved) | Required |
| `00-overview.md` | `specs/{NNN}-{feature}/00-overview.md` | Required |
| `assumptions.md` | `specs/{NNN}-{feature}/assumptions.md` (or staging) | Required |
| `issues.md` | `specs/{NNN}-{feature}/issues.md` | From WHY2 |
| `calibration-profile.yaml` | `knowledge-base/calibration-profile.yaml` | Mark `[ABSENT]` on cold start |
| `estimates-log.yaml` | `knowledge-base/estimates-log.yaml` | Mark `[ABSENT]` on cold start |
| `reasoning-journal.json` | `.specify/squad/staging/reasoning-journal.json` | Required |

**Verification before dispatch:** for each row, run `[ -f <path> ] && echo "OK $path" || echo "ABSENT $path"`. Absences are acceptable for `calibration-profile.yaml` and `estimates-log.yaml` only.

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

- **description:** "speckit-echelon-gatekeeper (GATEKEEPER): feasibility, estimation, prioritization, kill gate"

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

**MANDATORY — run before transitioning to phase2-strategic-overview:**

```bash
# Budget: definition.yaml phases[phase2-decide].budget_seconds = 1800
# Start phase2-decide timing if not already started (idempotent — skips if start_ts exists)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase2-decide 1800
```

Do NOT close phase2-decide here — it spans through phase2-strategic-overview and phase2-tracker-alignment. It closes in phase3-specialists.

Phase budget map for consistency across all transitions:

- `phase1-understand=2400`
- `phase2-decide=1800`
- `phase3-solution=2400`
- `phase4-build=7200`

**Transition:** `phases[phase2-strategic-overview]` — see `workflow/definition.yaml`
