# Phase: phase3-consensus
# Source: echelon.run.md §11 — CONSENSUS Phase (Parallel Validation)
# Agent: parallel — speckit-echelon-sage (SAGE) (WHY3), speckit-echelon-gatekeeper (GATEKEEPER) (ASSESS2), speckit-echelon-orchestrator (ORCHESTRATOR) (PLAN2)
# Executed by: Echelon staged-parallel harness

## 11. CONSENSUS Phase (Parallel Validation)

The harness dispatches **WHY3 and ASSESS2 in parallel, then PLAN2 sequentially**
after both Stage 1 results are complete. It never dispatches all three agents in
one parallel batch.

### 11.1 WHY3 Context Pack

Read these artifacts in `{spec_dir}/`:

- Spec and architecture artifacts: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`
- Governance artifact: `.specify/memory/constitution.md` (read-only)
- Planning artifacts: `tasks.md`, `critical-path.md`, `risk-matrix.md`, `dependencies.md`
- Test artifacts: `test-strategy.md`, `coverage-map.md`
- Specialist outputs, if present
- Harness-injected Certified Understanding Evidence report
- `agents/exploration/templates/sage-quality-gates-template.md`
- `agents/exploration/templates/sage-issues-template.md`
- `calibration-profile.yaml`
- `reasoning-journal.jsonl`

### 11.2 ASSESS2 Context Pack

Read these artifacts in `{spec_dir}/`:

- `spec.md`
- `plan.md` + `data-model.md` + `contracts/`
- `research.md`
- `tasks.md` + `test-strategy.md` + `coverage-map.md`
- `estimates.md` + `mvp-scope.md`
- `.specify/memory/constitution.md` (read-only team constraints)
- `extension/templates/estimates-template.md`
- `extension/templates/implementability-report-template.md`
- `reasoning-journal.jsonl`

### 11.3 PLAN2 Context Pack

Read these artifacts in `{spec_dir}/`:

- `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`
- `.specify/memory/constitution.md` (read-only governance)
- `tasks.md`, `critical-path.md`, `risk-matrix.md`, `dependencies.md`
- `test-strategy.md`, `coverage-map.md`
- WHY3 outputs: `quality-gates.md`, `issues.md`
- `implementability-report.md` (from ASSESS2 — dispatch ASSESS2 first, then PLAN2 reads its output)
- `reasoning-journal.jsonl`

### Dispatch — Two Stages (see `definition.yaml` `phase3-consensus.type: staged_parallel`)

This phase uses `type: staged_parallel`. **Always dispatch in the two stages below. NEVER dispatch all three agents in one parallel batch.** PLAN2 requires `implementability-report.md` from ASSESS2 — dispatching it simultaneously means it runs without that input.

**Stage 1 (parallel):** dispatch WHY3 and ASSESS2 together. Wait for BOTH to complete.

**WHY3:**

- **prompt:**

  ```xml
  <context>
  [include spec.md, read-only .specify/memory/constitution.md, plan.md, research.md, data-model.md, contracts/, tasks.md, critical-path.md, risk-matrix.md, dependencies.md, test-strategy.md, coverage-map.md, sage WHY3 output templates, calibration-profile.yaml, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **spec-validation mode** (WHY3 — consensus).
  When Product Input Contract paths are present, reject consensus while a normative unit remains `open_question` or `conflict`, and return the required structured product-input corrections.
  Read and interpret the harness-injected Certified Understanding Evidence report. Do not run validators, recalculate scores, or return controller-owned quality scores. Check cross-artifact consistency across ALL artifacts, including the read-only constitution snapshot. This is the final qualitative quality check. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "WHY3: final quality validation and cross-artifact consistency"

**ASSESS2:**

- **prompt:**

  ```xml
  <context>
  [include spec.md, plan.md, research.md, data-model.md, contracts/, tasks.md, test-strategy.md, coverage-map.md, estimates.md, mvp-scope.md, .specify/memory/constitution.md, extension/templates/estimates-template.md, extension/templates/implementability-report-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are GATEKEEPER. Read agents/feasibility/gatekeeper.md for your complete protocol. Operate as ASSESS2 — consensus-phase re-evaluation.
  Re-evaluate feasibility against the concrete architecture. Update `estimates.md` using the provided template, reconciling Phase A, Phase B, human-only, and AI-assisted scenarios; retain or revise the AI-assisted token and USD budgets with an explicit pricing basis. Perform the **6-point IMPLEMENTABILITY CHECK**: (1) Can a developer pick up each task without unstated knowledge? (2) Do tasks reference APIs/libraries/services that actually exist? (3) Are "parallel" tasks truly independent? (4) Does the tech stack match available team skills? (5) Are task descriptions self-contained? (6) Can each task be tested independently? Produce `implementability-report.md` using the provided template (scored per task: READY / NEEDS_CLARIFICATION / BLOCKED). You can flag but NOT kill at this stage — only CRITICAL feasibility issues route back to HOW. Put ASSESS2 task-readiness and effort metrics in `echelon_result.state_updates.implementability_metrics`; certified quality scores remain controller-owned. Produce outputs in `{spec_dir}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "ASSESS2: implementability check and effort re-estimation"

**Stage 2 (sequential):** after Stage 1 is fully complete, the harness verifies
the exact run-local `{spec_dir}/implementability-report.md`. A missing report
returns `BLOCKED` with `missing_consensus_prerequisite`; PLAN2 is not dispatched.

**PLAN2:**

- **prompt:**

  ```xml
  <context>
  [include spec.md, read-only .specify/memory/constitution.md, plan.md, research.md, data-model.md, contracts/, tasks.md, critical-path.md, risk-matrix.md, dependencies.md, test-strategy.md, coverage-map.md, quality-gates.md, issues.md, implementability-report.md from ASSESS2, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol. Operate as PLAN2 — consensus-phase plan revision.
  When Product Input Contract paths are present, repair any requirement mapping that lacks a canonical target-owned task and return `product_input_updates` using the exact canonical fields `input_unit_id`, `disposition`, `rationale`, `spec_ids`, `task_ids`, and `targets`; do not edit the controller-owned ledger directly.
  Treat `.specify/memory/constitution.md` as read-only governance context. Do not edit, rewrite, append to, or output it.
  Re-evaluate task dependencies and task-to-spec coverage against spec.md, plan.md, contracts/, coverage-map.md, WHY3 issues, and ASSESS2 implementability feedback. Update critical path if sequencing changed. Validate all specialist and test-strategy outputs have corresponding tasks. Incorporate implementability feedback — split unclear tasks, add missing context, and add missing requirement/test tasks. Produce outputs in `{spec_dir}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "PLAN2: plan revision incorporating implementability feedback"

### Deterministic Tasks Recertification

After PLAN2 completes, `phase3-consensus` always transitions to
`phase3-consensus-tasks-lexicon`. This provider-free deterministic node
recertifies the on-disk planning artifacts because PLAN2 may have revised
`tasks.md`.

- `repair` routes to `phase3-plan` with `increment_iteration`.
- `block` routes normally to `terminal-blocked`.
- `proceed` and `proceed_with_warning` preserve the consensus verdict routing
  below.

The node writes `tasks-lexicon-report.json` and the controller-owned
`tasks_lexicon_*` state. WHY3, ASSESS2, and PLAN2 do not calculate or report
that state.

### Consensus Gate Check

Read outputs from all three consensus agents:

- **ALL PASS** (no CRITICAL issues, quality gates met, all tasks READY or NEEDS_CLARIFICATION with fixes applied) → proceed to FINALIZE
- **MINOR issues only** → MANAGER resolves directly (update artifacts, log reasoning). Re-run consensus if changes are significant.
- **CRITICAL issues** → route back to the responsible phase:
  - WHY3 CRITICAL spec issues → back to WHAT
  - ASSESS2 CRITICAL feasibility issues → back to HOW
  - PLAN2 missing tasks for specialist outputs → back to PLAN
  - Increment iteration. Check limits.

The controller owns the `phase4-build` timing window declared in
`workflow/definition.yaml`. It opens after `phase3-plan`, remains open through
CONSENSUS and FINALIZE, and closes after successful `phase4-document` execution.
Timing stays in `telemetry/events.jsonl`; agents do not start, stop, or report
phase timers.

**Transition:** `phases[phase3-consensus-tasks-lexicon]` — see
`workflow/definition.yaml`
