# Phase: phase3-consensus
# Source: echelon.run.md §11 — CONSENSUS Phase (Parallel Validation)
# Agent: parallel — speckit-echelon-sage (SAGE) (WHY3), speckit-echelon-gatekeeper (GATEKEEPER) (ASSESS2), speckit-echelon-orchestrator (ORCHESTRATOR) (PLAN2)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching consensus agents

## 11. CONSENSUS Phase (Parallel Validation)

This phase runs **WHY3 + ASSESS2 + PLAN2 in parallel** using multiple Agent tool calls in a single message. If specialists are still active, include them in the parallel dispatch.

### 11.1 WHY3 Context Pack

- All artifacts in `specs/{feature}/` (spec, plan, tasks, specialist outputs)
- Understanding access (via `speckit.echelon.understanding-validate` Skill tool)
- `calibration-profile.yaml`
- `reasoning-journal.json`

### 11.2 ASSESS2 Context Pack

- `plan.md` + `data-model.md` + `contracts/`
- `tasks.md` + `estimates.md`
- `constitution.md` (team constraints)
- `reasoning-journal.json`

### 11.3 PLAN2 Context Pack

- Updated `plan.md` + `test-strategy.md`
- All specialist outputs
- `implementability-report.md` (from ASSESS2 — dispatch ASSESS2 first, then PLAN2 reads its output)
- `reasoning-journal.json`

### Dispatch (Parallel)

Dispatch WHY3 and ASSESS2 in parallel (single message, two Agent tool calls):

**WHY3:**

- **prompt:**

  ```xml
  <context>
  [include all artifacts in specs/{feature}/, calibration-profile.yaml, reasoning-journal.json]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **spec-validation mode** (WHY3 — consensus).
  Run full Understanding quality gates. Check cross-artifact consistency across ALL artifacts. This is the final quality check. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "WHY3: final quality validation and cross-artifact consistency"

**ASSESS2:**

- **prompt:**

  ```xml
  <context>
  [include plan.md, data-model.md, contracts/, tasks.md, estimates.md, constitution.md, reasoning-journal.json]
  </context>

  <instructions>
  You are GATEKEEPER. Read agents/feasibility/gatekeeper.md for your complete protocol. Operate as ASSESS2 — consensus-phase re-evaluation.
  Re-evaluate feasibility against the concrete architecture. Update effort estimates with architectural complexity. Perform the **6-point IMPLEMENTABILITY CHECK**: (1) Can a developer pick up each task without unstated knowledge? (2) Do tasks reference APIs/libraries/services that actually exist? (3) Are "parallel" tasks truly independent? (4) Does the tech stack match available team skills? (5) Are task descriptions self-contained? (6) Can each task be tested independently? Produce `implementability-report.md` (scored per task: READY / NEEDS_CLARIFICATION / BLOCKED). You can flag but NOT kill at this stage — only CRITICAL feasibility issues route back to HOW. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "ASSESS2: implementability check and effort re-estimation"

After WHY3 and ASSESS2 complete, dispatch PLAN2:

**PLAN2:**

- **prompt:**

  ```xml
  <context>
  [include updated plan.md, test-strategy.md, all specialist outputs, implementability-report.md from ASSESS2, reasoning-journal.json]
  </context>

  <instructions>
  You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol. Operate as PLAN2 — consensus-phase plan revision.
  Re-evaluate task dependencies with specialist-added tasks. Update critical path if specialist work changed sequencing. Validate all specialist outputs have corresponding tasks. Incorporate implementability feedback — split unclear tasks, add missing context. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
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
# At run close — in phase4-document BEFORE setting state.json.status = "done"
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" end_phase phase4-build
```

Then append one `timing_summary` journal entry per phase to `reasoning-journal.jsonl`. The anomaly reason enum value for Tier 1 is exactly `EXCEEDED_BUDGET_20_PERCENT`.

**Transition:** `phases[phase4-document]` — see `workflow/definition.yaml`
