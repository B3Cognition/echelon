# Phase: phase3-plan
# Source: echelon.run.md §10 — PLAN Phase (Task Breakdown)
# Agent: speckit-echelon-orchestrator (ORCHESTRATOR)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-orchestrator (ORCHESTRATOR)

## 10. PLAN Phase (Task Breakdown)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `research.md` + `data-model.md`
- `spec.md` (canonical rich feature specification and requirement IDs)
- `constitution.md` (read-only published Phase A governance snapshot)
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
  [include spec.md, read-only constitution.md, plan.md, research.md, data-model.md, contracts/, test-strategy.md, risk data from specialists, planning output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol.
  Treat IMPLEMENTATION_TARGETS from the squad context as authoritative. Every canonical task row must include exactly one `target=<declared-target>` value, and every file path must be valid for that target. Split cross-target work into dependency-linked tasks. Never infer or declare a target from generated file paths.
  When Product Input Contract paths are present, map every included `IN-REQ-*` unit to canonical `req=` task rows and their declared `target=` values. Every listed task ID must directly intersect that unit's `spec_ids` through its canonical `req=` value; do not list a phase-neighbouring or merely related task. Do not mark a contextual or illustrative unit `included` with empty `spec_ids` or `task_ids`: map it to a concrete requirement and task, or use `excluded`/`duplicate` with an evidence-backed rationale. Return those task IDs and targets in `echelon_result.product_input_updates`, preserving the exact canonical fields `input_unit_id`, `disposition`, `rationale`, `spec_ids`, `task_ids`, and `targets`; the controller writes the canonical ledger.
  Treat `constitution.md` as read-only governance context. Every task decomposition and risk/dependency decision must respect its non-negotiable principles. Do not edit, rewrite, append to, or output `constitution.md`.
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

The controller verifies all four required outputs after dispatch. It also
validates canonical task rows, Lexicon requirements coverage, and every task's
explicit `target=` metadata plus its `**Files:**` paths against the run's
declared targets. The validation never writes `targets.yml`. Missing,
undeclared, mismatched, or cross-target ownership must be repaired or split
before transitioning.

Phase timing is controller-owned. The harness closes `phase3-solution`, opens
`phase4-build`, and writes append-only telemetry before dispatching consensus
agents.

**Transition:** `phases[phase3-understanding]` — see `workflow/definition.yaml`

### Tasks Lexicon Gate — Controlled-Outcome Routing

When `lexicon_gate.artifacts.tasks.enabled`, ORCHESTRATOR authors `tasks.md` in
the TASKS grammar. After the dispatch, the controller validates the on-disk
artifact and writes `state.json.tasks_lexicon_pass`; the model never owns that
Boolean verdict.

**Controlled-outcome routing.** After the dispatch, the controller validates
`tasks.md` against the configured `spec_ref` and glossary, persists the
certified outcome, and reads `state.json.tasks_lexicon_pass`:
- `tasks_lexicon_pass == true` → proceed to `phase3-understanding` (controller-certified Understanding analysis and then consensus
  scoring runs there, once, on a structurally-clean `tasks.md`).
- `tasks_lexicon_pass == false AND tasks_lexicon_attempts < max_repair_attempts AND iteration < max_iterations`
  → re-dispatch `phase3-plan` (`increment_iteration`). This is the only condition that
  re-dispatches ORCHESTRATOR on the Lexicon outcome — see the transitions in
  `workflow/definition.yaml`.
- `tasks_lexicon_attempts >= max_repair_attempts` (or the secondary `iteration >= max_iterations` cap)
  → honor `lexicon_gate.on_exhausted`:
  `warn` → proceed to `phase3-understanding` with a `lexicon_gate_exhausted` warning journal entry;
  `block` → set `plan_status: blocked`, `blocked_reason: "tasks lexicon gate not satisfied"`, stop.

**State updates (added to the dispatch's `echelon_result` block when a repair
attempt was made):**

```yaml
echelon_result:
  state_updates:
    tasks_lexicon_attempts: <int>
```

> Registration invariant: `tasks_lexicon_pass` is controller-owned, exactly as
> `lexicon_pass` is for phase1-what. The re-dispatch guard in
> `definition.yaml` references only `lexicon_gate.enabled` +
> `tasks_lexicon_pass` so it stays deterministically evaluable — it must NOT
> reference unresolvable config paths.

The controller repeats the same certification after PLAN2 because PLAN2 may
revise `tasks.md`. A failed post-PLAN2 certificate routes back to `phase3-plan`
with the structured findings in `{spec_dir}/tasks-lexicon-report.json`.
