# Phase: phase2-decide
# Source: echelon.run.md §6 — ASSESS Phase (Kill Gate)
# Agent: speckit-echelon-gatekeeper (GATEKEEPER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-gatekeeper (GATEKEEPER)

## 6. ASSESS Phase (Kill Gate)

### Context Pack Assembly — MUST INCLUDE

Every file below MUST be included (or marked `[ABSENT: <path>]` if missing). Silently omitting any of these is a routing error — speckit-echelon-gatekeeper (GATEKEEPER) calibrates against the calibration profile, scopes against the glossary, and re-uses prior estimates if available.

| File | Path | Notes |
| --- | --- | --- |
| `spec.md` | `{spec_dir}/spec.md` | Required |
| `glossary.md` | `{spec_dir}/glossary.md` (or `${STAGING_DIR}/glossary.md` if not yet moved) | Required |
| `00-overview.md` | `{spec_dir}/00-overview.md` | Required |
| `assumptions.md` | `{spec_dir}/assumptions.md` (or staging) | Required |
| `issues.md` | `{spec_dir}/issues.md` | From WHY2 |
| `calibration-profile.yaml` | `knowledge-base/calibration-profile.yaml` | Mark `[ABSENT]` on cold start |
| `estimates-log.yaml` | `knowledge-base/estimates-log.yaml` | Mark `[ABSENT]` on cold start |
| `extension/templates/feasibility-template.md` | `extension/templates/feasibility-template.md` | Required |
| `extension/templates/prioritization-template.md` | `extension/templates/prioritization-template.md` | Required |
| `extension/templates/estimates-template.md` | `extension/templates/estimates-template.md` | Required |
| `extension/templates/mvp-scope-template.md` | `extension/templates/mvp-scope-template.md` | Required |
| `extension/templates/kill-report.md` | `extension/templates/kill-report.md` | Required |
| `reasoning-journal.jsonl` | `${SQUAD_DIR}/reasoning-journal.jsonl` | Required |

**Verification before dispatch:** for each row, run `[ -f <path> ] && echo "OK $path" || echo "ABSENT $path"`. Absences are acceptable for `calibration-profile.yaml` and `estimates-log.yaml` only.

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include spec.md, glossary.md, assumptions.md, issues.md from WHY2, calibration-profile.yaml, estimates-log.yaml, gatekeeper first-pass templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are GATEKEEPER. Read agents/feasibility/gatekeeper.md for your complete protocol.
  Evaluate feasibility (can this be built within constraints?). Estimate effort using Function Point Analysis adjusted by calibration data. Prioritize features with Kano + RICE. Scope MVP. **Kill gate:** if unfeasible or all low-priority, produce a kill report using `extension/templates/kill-report.md`. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
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

**MANDATORY — run before transitioning to phase2-strategic-overview:**

```bash
# Budget: definition.yaml phases[phase2-decide].budget_seconds = 1800
# Start phase2-decide timing if not already started (idempotent — skips if start_ts exists)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase2-decide 1800
```

Always leave phase2-decide open here — it spans through phase2-strategic-overview and phase2-tracker-alignment. Do NOT close it until phase3-specialists.

Phase budget map for consistency across all transitions:

- `phase1-understand=2400`
- `phase2-decide=1800`
- `phase3-solution=2400`
- `phase4-build=7200`

**Transition:** `phases[phase2-strategic-overview]` — see `workflow/definition.yaml`

### Feasibility Structural Gate — Controlled-Outcome Routing

When `governance.enabled` and the artifact has `tier: structural`, GATEKEEPER authors
`feasibility.md` in the STRUCTURAL grammar and runs the in-dispatch
`$LEXICON validate --type structural --artifact feasibility` repair loop
(see `agents/feasibility/gatekeeper.md §Structural Gate Mode`). COMMANDER owns the
re-dispatch decision on the controlled outcome and is the sole writer to `state.json`;
COMMANDER does NOT run `lexicon` itself.

> **Fail-open note:** If the gate is enabled but GATEKEEPER returns no
> `feasibility_structural_pass` flag, routing treats it as passed (fail-open, consistent
> with `on_exhausted: warn`).

**Controlled-outcome routing.** After the dispatch, COMMANDER persists GATEKEEPER's
`echelon_result.state_updates` and reads `state.json.feasibility_structural_pass`:
- `feasibility_structural_pass == true` → proceed to `phase2-strategic-overview` (normal forward flow).
- `feasibility_structural_pass == false AND iteration < max_iterations` → re-dispatch `phase2-decide`
  (`increment_iteration`). This is the only condition that re-dispatches GATEKEEPER on the
  structural outcome — see the transitions in `workflow/definition.yaml`.
- `iteration >= max_iterations` → honor `governance.on_exhausted`:
  `warn` → proceed to `phase2-strategic-overview` with a `structural_gate_exhausted` warning journal entry;
  `block` → set `status: blocked`, `blocked_reason: "feasibility structural gate not satisfied"`, stop.

**State updates (added to the dispatch's `echelon_result` block when the gate is enabled):**

```yaml
echelon_result:
  state_updates:
    feasibility_structural_pass: true     # authoritative validator verdict for this pass (true|false)
    feasibility_structural_attempts: <int>
```

> Registration invariant: `feasibility_structural_pass` is an authoritative state key (declared in
> this node's `outputs:` and read here), exactly as `lexicon_pass` is for phase1-what. The re-dispatch
> guard in `definition.yaml` references only `governance.enabled` + `feasibility_structural_pass` so it
> stays deterministically evaluable — it must NOT reference unresolvable config paths.
