# Phase: phase3-plan
# Source: echelon.run.md §10 — PLAN Phase (Task Breakdown)
# Agent: speckit-echelon-orchestrator (ORCHESTRATOR)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-orchestrator (ORCHESTRATOR)

## 10. PLAN Phase (Task Breakdown)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `research.md` + `data-model.md`
- `contracts/` + `test-strategy.md`
- Risk data from specialists (threat-model.md, performance-requirements.md, etc.)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include plan.md, research.md, data-model.md, contracts/, test-strategy.md, risk data from specialists, reasoning-journal.json]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol.
  Break the architecture into executable tasks (foundation, features, polish). Identify the critical path. Map task dependencies and parallelization. Assess risk per task. Include test tasks from test-strategy.md. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-orchestrator (ORCHESTRATOR): task breakdown, critical path, dependencies, risk"

### Expected Outputs — EXACT FILENAMES

ORCHESTRATOR produces these four files in `specs/{NNN}-{feature}/` with **exactly** these names. Naming variants break downstream consumers (CONSENSUS, build phase, harness).

| Required filename | Purpose |
| --- | --- |
| `tasks.md` | Task list |
| `critical-path.md` | Critical path analysis |
| `risk-matrix.md` | Per-task risk scoring |
| `dependencies.md` | Task dependency map |

**NEVER** substitute or omit:

- NEVER write `dependency-graph.md` instead of `dependencies.md`.
- NEVER omit `risk-matrix.md` (some risk content may also live in tasks.md, but the standalone file is required).
- NEVER rename to `task-list.md`, `plan.md`, or any other variant.

**Verification (run before transition to phase3-consensus):**

```bash
for f in tasks.md critical-path.md risk-matrix.md dependencies.md; do
  [ -f "specs/${SPEC_DIR}/$f" ] || { echo "ERROR: ORCHESTRATOR missing $f" >&2; exit 1; }
done
```

**MANDATORY — run before transitioning to phase3-consensus:**

```bash
# Close phase3-solution (writes end_ts, elapsed_seconds, over_budget)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" end_phase phase3-solution
# Open phase4-build
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase4-build 7200
```

Confirm `state.json.phase_timings` is updated before dispatching consensus agents.

**Transition:** `phases[phase3-consensus]` — see `workflow/definition.yaml`
