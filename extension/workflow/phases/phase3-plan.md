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
- `extension/templates/tasks-template.md`
- `extension/templates/task-entry-fragment.md`
- `extension/templates/task-checkpoint-fragment.md`
- `extension/templates/critical-path-template.md`
- `extension/templates/planning-risk-matrix-template.md`
- `extension/templates/dependencies-template.md`
- `reasoning-journal.jsonl`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include plan.md, research.md, data-model.md, contracts/, test-strategy.md, risk data from specialists, planning output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol.
  Break the architecture into executable tasks (foundation, features, polish). Use the provided planning templates; every executable task must start with a canonical task row. Use `T-###` for normal tasks and `T-S##` / `T-S##x` only for spike or user-decision tasks. Identify the critical path. Map task dependencies and parallelization. Assess risk per task. Include test tasks from test-strategy.md. Produce outputs in `{spec_dir}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-orchestrator (ORCHESTRATOR): task breakdown, critical path, dependencies, risk"

### Expected Outputs — EXACT FILENAMES

speckit-echelon-orchestrator (ORCHESTRATOR) produces these four files in `{spec_dir}/` with **exactly** these names. Naming variants break downstream consumers (CONSENSUS, build phase, harness).

| Required filename | Purpose |
| --- | --- |
| `tasks.md` | Task list |
| `critical-path.md` | Critical path analysis |
| `risk-matrix.md` | Per-task risk scoring |
| `dependencies.md` | Task dependency map |

**Always** produce the exact required filenames. **NEVER** substitute or omit:

- Always write `dependencies.md`; NEVER write `dependency-graph.md` instead.
- Always include standalone `risk-matrix.md`; NEVER omit it (some risk content may also live in tasks.md, but the standalone file is required).
- Always keep the specified filenames; NEVER rename to `task-list.md`, `plan.md`, or any other variant.

**Verification (run before transition to phase3-consensus):**

```bash
for f in tasks.md critical-path.md risk-matrix.md dependencies.md; do
  [ -f "{spec_dir}/$f" ] || { echo "ERROR: speckit-echelon-orchestrator (ORCHESTRATOR) missing $f" >&2; exit 1; }
done
```

Also verify `tasks.md` uses canonical task rows:

```bash
python -m harness validate-tasks "{spec_dir}/tasks.md"
```

**MANDATORY — run before transitioning to phase3-consensus:**

```bash
# Budgets: definition.yaml phases[phase3-plan].timing_window_transition
#   close: phase3-solution (open_budget_seconds=2400)
#   open:  phase4-build (open_budget_seconds=7200)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" end_phase phase3-solution
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase4-build 7200
```

Confirm `state.json.phase_timings` is updated before dispatching consensus agents.

**Transition:** `phases[phase3-consensus]` — see `workflow/definition.yaml`

### Tasks Lexicon Gate — Controlled-Outcome Routing

When `lexicon_gate.artifacts.tasks.enabled`, ORCHESTRATOR authors `tasks.md` in the TASKS
grammar and runs the in-dispatch `lexicon validate --type tasks` repair loop (the "fix" —
see `agents/solution/orchestrator.md §Tasks Gate Mode`). COMMANDER owns the re-dispatch
decision on the controlled outcome (the "re-dispatch") and is the sole writer to `state.json`;
COMMANDER does NOT run `lexicon` itself.

**Controlled-outcome routing.** After the dispatch, COMMANDER persists ORCHESTRATOR's
`echelon_result.state_updates` and reads `state.json.tasks_lexicon_pass`:
- `tasks_lexicon_pass == true` → proceed to `phase3-consensus` (soft `understanding`/consensus
  scoring runs there, once, on a structurally-clean `tasks.md`).
- `tasks_lexicon_pass == false AND iteration < max_iterations` → re-dispatch `phase3-plan`
  (`increment_iteration`). This is the only condition that re-dispatches ORCHESTRATOR on the
  Lexicon outcome — see the transitions in `workflow/definition.yaml`.
- `iteration >= max_iterations` → honor `lexicon_gate.on_exhausted`:
  `warn` → proceed to `phase3-consensus` with a `lexicon_gate_exhausted` warning journal entry;
  `block` → set `plan_status: blocked`, `blocked_reason: "tasks lexicon gate not satisfied"`, stop.

**State updates (added to the dispatch's `echelon_result` block when the gate is enabled):**

```yaml
echelon_result:
  state_updates:
    tasks_lexicon_pass: true     # authoritative validator verdict for this pass (true|false)
    tasks_lexicon_attempts: <int>
```

> Registration invariant: `tasks_lexicon_pass` is an authoritative state key (declared in this
> node's `outputs:` and read here), exactly as `lexicon_pass` is for phase1-what. The re-dispatch
> guard in `definition.yaml` references only `lexicon_gate.enabled` + `tasks_lexicon_pass` so it
> stays deterministically evaluable — it must NOT reference unresolvable config paths.
