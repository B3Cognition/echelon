# Phase: phase3-plan
# Source: echelon.run.md §10 — PLAN Phase (Task Breakdown)
# Agent: echelon.orchestrator (ORCHESTRATOR)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.orchestrator (ORCHESTRATOR)

## 10. PLAN Phase (Task Breakdown)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `research.md` + `data-model.md`
- `spec.md` (canonical rich feature specification and requirement IDs)
- `.echelon/constitution.md` (controller-injected, read-only Phase A governance)
- `contracts/` + `test-strategy.md`
- Risk data from specialists (threat-model.md, performance-requirements.md, etc.)
- `.echelon/runtime/templates/tasks-template.md`
- `.echelon/runtime/templates/task-entry-fragment.md`
- `.echelon/runtime/templates/task-checkpoint-fragment.md`
- `.echelon/runtime/templates/critical-path-template.md`
- `.echelon/runtime/templates/planning-risk-matrix-template.md`
- `.echelon/runtime/templates/dependencies-template.md`
- `reasoning-journal.jsonl`

### Dispatch

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include spec.md, controller-injected read-only .echelon/constitution.md context, plan.md, research.md, data-model.md, contracts/, test-strategy.md, risk data from specialists, planning output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read subagents/echelon.orchestrator.md for your complete protocol.
  Treat IMPLEMENTATION_TARGETS from the squad context as authoritative. Every canonical task row must include exactly one `target=<declared-target>` value, and every file path must be valid for that target. Split cross-target work into dependency-linked tasks. Never infer or declare a target from generated file paths.
  When Product Input Contract paths are present, map every included `IN-REQ-*` unit to canonical `req=` task rows and their declared `target=` values. Every listed task ID must directly intersect that unit's `spec_ids` through its canonical `req=` value; do not list a phase-neighbouring or merely related task. Do not mark a contextual or illustrative unit `included` with empty `spec_ids` or `task_ids`: map it to a concrete requirement and task, or use `excluded`/`duplicate` with an evidence-backed rationale. Return those task IDs and targets in `echelon_result.product_input_updates`, preserving the exact canonical fields `input_unit_id`, `disposition`, `rationale`, `spec_ids`, `task_ids`, and `targets`; the controller writes the canonical ledger.
  Treat the injected `.echelon/constitution.md` section as read-only governance context. Every task decomposition and risk/dependency decision must respect its non-negotiable principles. Do not search for a spec-local copy and do not edit, rewrite, append to, or output the canonical constitution.
  Break the architecture into executable tasks (foundation, features, polish). Use the provided planning templates; every executable task must start with a canonical task row. Use `T-###` for normal tasks and `T-S##` / `T-S##x` only for spike or user-decision tasks. Identify the critical path. Map task dependencies and parallelization. Assess risk per task. Include test tasks from test-strategy.md. Produce outputs in `{spec_dir}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon.orchestrator (ORCHESTRATOR): task breakdown, critical path, dependencies, risk"

### Expected Outputs — EXACT FILENAMES

echelon.orchestrator (ORCHESTRATOR) produces these four files in `{spec_dir}/` with **exactly** these names. Naming variants break downstream consumers (CONSENSUS, build phase, harness).

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

The explicit `phase3-tasks-lexicon` deterministic node verifies all four
required outputs after this authoring phase. It also validates canonical task
rows, Lexicon requirements coverage, and every task's explicit `target=`
metadata plus its `**Files:**` paths against the run's declared targets. The
validation never writes `targets.yml`. Missing, undeclared, mismatched, or
cross-target ownership must be repaired or split before transitioning.

Phase timing is controller-owned. The harness closes `phase3-solution`, opens
`phase4-build`, and writes append-only telemetry before dispatching consensus
agents.

**Transition:** `phases[phase3-tasks-lexicon]` — see `workflow/definition.yaml`

### Tasks Lexicon Gate — Controlled-Outcome Routing

When `lexicon_gate.artifacts.tasks.enabled`, ORCHESTRATOR authors `tasks.md` in
the TASKS grammar and reports no Lexicon verdict or attempt count. The workflow
then always advances to `phase3-tasks-lexicon`. That provider-free deterministic
node validates `tasks.md` against the configured `spec_ref` and glossary,
writes `{spec_dir}/tasks-lexicon-report.json`, and persists these
controller-owned fields:

- `state.json.tasks_lexicon_action`
- `state.json.tasks_lexicon_pass`
- `state.json.tasks_lexicon_attempts`
- `state.json.tasks_lexicon_findings`
- `state.json.tasks_lexicon_report`
- `state.json.blocked_reason`, when required

The deterministic node validates and chooses exactly one routing action:

- `repair` → re-dispatch `phase3-plan` with `increment_iteration`
- `proceed` or `proceed_with_warning` → advance to `phase3-understanding`
- `block` → advance normally to `terminal-blocked`

Because the result is produced by its own workflow node, state advancement and
phase checkpointing use the same controller path as other successful nodes.
There is no post-dispatch validation hook on ORCHESTRATOR. The separate
`phase3-consensus-tasks-lexicon` node repeats this certification after PLAN2,
because PLAN2 may revise `tasks.md`.
