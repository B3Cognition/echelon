# Phase: phase3-consensus
# Source: echelon.run.md §11 — CONSENSUS Phase (Parallel Validation)
# Agent: parallel — speckit-echelon-sage (SAGE) (WHY3), speckit-echelon-gatekeeper (GATEKEEPER) (ASSESS2), speckit-echelon-orchestrator (ORCHESTRATOR) (PLAN2)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching consensus agents

## 11. CONSENSUS Phase (Parallel Validation)

This phase runs **WHY3 + ASSESS2 + PLAN2 in parallel** using multiple Agent tool calls in a single message. If specialists are still active, include them in the parallel dispatch.

### 11.1 WHY3 Context Pack

Read these artifacts in `{spec_dir}/`:

- Spec and architecture artifacts: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`
- Governance artifact: `constitution.md` (read-only published Phase A snapshot)
- Planning artifacts: `tasks.md`, `critical-path.md`, `risk-matrix.md`, `dependencies.md`
- Test artifacts: `test-strategy.md`, `coverage-map.md`
- Specialist outputs, if present
- Understanding access (via `speckit.echelon.understanding-validate` Skill tool)
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
- `constitution.md` (team constraints)
- `extension/templates/implementability-report-template.md`
- `reasoning-journal.jsonl`

### 11.3 PLAN2 Context Pack

Read these artifacts in `{spec_dir}/`:

- `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`
- `constitution.md` (read-only published Phase A governance snapshot)
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
  [include spec.md, read-only constitution.md, plan.md, research.md, data-model.md, contracts/, tasks.md, critical-path.md, risk-matrix.md, dependencies.md, test-strategy.md, coverage-map.md, sage WHY3 output templates, calibration-profile.yaml, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **spec-validation mode** (WHY3 — consensus).
  When Product Input Contract paths are present, reject consensus while a normative unit remains `open_question` or `conflict`, and return the required structured product-input corrections.
  Run full Understanding quality gates via `speckit.echelon.understanding-validate`. Check cross-artifact consistency across ALL artifacts, including the read-only constitution snapshot. This is the final quality check. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "WHY3: final quality validation and cross-artifact consistency"

**ASSESS2:**

- **prompt:**

  ```xml
  <context>
  [include spec.md, plan.md, research.md, data-model.md, contracts/, tasks.md, test-strategy.md, coverage-map.md, estimates.md, mvp-scope.md, constitution.md, extension/templates/implementability-report-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are GATEKEEPER. Read agents/feasibility/gatekeeper.md for your complete protocol. Operate as ASSESS2 — consensus-phase re-evaluation.
  Re-evaluate feasibility against the concrete architecture. Update effort estimates with architectural complexity. Perform the **6-point IMPLEMENTABILITY CHECK**: (1) Can a developer pick up each task without unstated knowledge? (2) Do tasks reference APIs/libraries/services that actually exist? (3) Are "parallel" tasks truly independent? (4) Does the tech stack match available team skills? (5) Are task descriptions self-contained? (6) Can each task be tested independently? Produce `implementability-report.md` using the provided template (scored per task: READY / NEEDS_CLARIFICATION / BLOCKED). You can flag but NOT kill at this stage — only CRITICAL feasibility issues route back to HOW. Put ASSESS2 task-readiness and effort metrics in `echelon_result.state_updates.implementability_metrics`; `quality_scores` is reserved for list-shaped WHY/SAGE quality gate scores. Produce outputs in `{spec_dir}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "ASSESS2: implementability check and effort re-estimation"

**Stage 2 (sequential):** after Stage 1 is fully complete, verify `implementability-report.md` exists, then dispatch PLAN2:

```bash
[ -f "specs/${SPEC_DIR}/implementability-report.md" ] || { echo "ERROR: ASSESS2 did not produce implementability-report.md — cannot dispatch PLAN2" >&2; exit 1; }
```

**PLAN2:**

- **prompt:**

  ```xml
  <context>
  [include spec.md, read-only constitution.md, plan.md, research.md, data-model.md, contracts/, tasks.md, critical-path.md, risk-matrix.md, dependencies.md, test-strategy.md, coverage-map.md, quality-gates.md, issues.md, implementability-report.md from ASSESS2, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol. Operate as PLAN2 — consensus-phase plan revision.
  When Product Input Contract paths are present, repair any requirement mapping that lacks a canonical target-owned task and return `product_input_updates`; do not edit the controller-owned ledger directly.
  Treat `constitution.md` as read-only governance context. Do not edit, rewrite, append to, or output `constitution.md`.
  Re-evaluate task dependencies and task-to-spec coverage against spec.md, plan.md, contracts/, coverage-map.md, WHY3 issues, and ASSESS2 implementability feedback. Update critical path if sequencing changed. Validate all specialist and test-strategy outputs have corresponding tasks. Incorporate implementability feedback — split unclear tasks, add missing context, and add missing requirement/test tasks. Produce outputs in `{spec_dir}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "PLAN2: plan revision incorporating implementability feedback"

### Consensus Gate Check

Read outputs from all three consensus agents:

- **ALL PASS** (no CRITICAL issues, quality gates met, all tasks READY or NEEDS_CLARIFICATION with fixes applied) → proceed to FINALIZE
- **MINOR issues only** → MANAGER resolves directly (update artifacts, log reasoning). Re-run consensus if changes are significant.
- **CRITICAL issues** → route back to the responsible phase:
  - WHY3 CRITICAL spec issues → back to WHAT
  - ASSESS2 CRITICAL feasibility issues → back to HOW
  - PLAN2 missing tasks for specialist outputs → back to PLAN
  - Increment iteration. Check limits.

**MANDATORY — run before transitioning to phase4-document:**

```bash
# Budget: definition.yaml phases[phase3-plan].timing_window_transition.open_budget_seconds = 7200
# Ensure phase4-build is open (idempotent — skips if already started)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase4-build 7200
```

phase4-build stays open through FINALIZE. Close it in phase4-document §12 before setting `status: done`:

```bash
# At run close — in phase4-document BEFORE returning status: done
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" end_phase phase4-build
```

Then return one `timing_summary` journal entry per phase in `echelon_result.journal_entries`. The anomaly reason enum value for Tier 1 is exactly `EXCEEDED_BUDGET_20_PERCENT`.

**Transition:** `phases[phase4-document]` — see `workflow/definition.yaml`
