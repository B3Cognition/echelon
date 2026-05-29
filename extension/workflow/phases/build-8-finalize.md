# Phase: build-8-finalize
# Source: echelon.build.md §8–§12 — Build Complete through Harness Integration
# Read by: speckit-echelon-commander (COMMANDER) after all phase checkpoints pass

## 8. Build Complete (BUILD_DONE)

After all tasks are built and all phase checkpoints pass:

### 8.1 Final Integration

Run speckit-echelon-integrator (INTEGRATOR) one last time against the complete codebase (all phases combined).

### 8.1b Engineering Manager Sign-Off

Before completion, dispatch speckit-echelon-engineering-manager (ENGINEERING MANAGER) with:

- `tasks.md`
- `spec.md`
- `traceability-matrix.md`
- `coverage-map.md`
- `process-metrics.md`
- `integration-report.md`
- `progress-report.md`
- all build gate reports
- `state.json`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **subagent_type:** `speckit-echelon-engineering-manager`
- **prompt:**

  ```xml
  <context>
  [include tasks.md, spec.md, traceability-matrix.md, coverage-map.md, process-metrics.md, integration-report.md, progress-report.md, all build gate reports, state.json, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ENGINEERING MANAGER. Read agents/build/engineering-manager.md for your complete protocol.
  Validate workflow compliance, report consistency, and readiness for final verification.
  </instructions>
  ```

- **description:** "speckit-echelon-engineering-manager (ENGINEERING MANAGER): final pre-verification sign-off"

speckit-echelon-engineering-manager (ENGINEERING MANAGER) must confirm:

1. Spec-kit task workflow was actually followed.
2. Task status, state tracking, and reports are internally consistent.
3. The build is ready for full speckit-echelon-verification (VERIFICATION).
4. **`verify.sh` exists and contains a smoke test** (see below).

If any of these fail, always route to rework first. Do not proceed to BUILD_DONE.

### 8.1b.1 verify.sh Smoke Test Requirement (MANDATORY)

Every build must produce a repo-root `verify.sh` that starts the produced application or artifact and proves it responds. Unit tests alone are not sufficient.

For complete smoke-test patterns, Next.js-specific checks, and stack-specific examples, load `workflow/phases/appendices/build-8-verify-gates.md` before ENGINEERING MANAGER sign-off or when IMPLEMENTER needs to create or repair `verify.sh`.

If `verify.sh` does not contain a smoke test, speckit-echelon-engineering-manager (ENGINEERING MANAGER) must request speckit-echelon-implementer (IMPLEMENTER) add one before sign-off. This is not optional.

### 8.1b.2 verify.sh Security and License Gate (MANDATORY)

Every `verify.sh` must run security and dependency license checks after the smoke test, inside the same Docker sandbox.

speckit-echelon-implementer (IMPLEMENTER) must select commands for every detected ecosystem and add them to `verify.sh` after the smoke test block. If an audit or license check fails, `verify.sh` must exit non-zero so the harness marks the build as failed.

For exact commands, permitted licenses, and polyglot handling, load `workflow/phases/appendices/build-8-verify-gates.md`.

### 8.1c Final Verification

Dispatch speckit-echelon-verification (VERIFICATION) after final integration and EM pre-check.

Use the Agent tool:

- **subagent_type:** `speckit-echelon-verification`
- **prompt:**

  ```xml
  <context>
  [include spec.md, all implemented code, all gate reports, traceability-matrix.md, coverage-map.md, state.json, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are VERIFICATION agent. Read agents/build/verification.md for your complete protocol.
  Run full backpropagation verification against spec requirements.
  Produce `gap-report.md`, `excess-report.md`, updated `traceability-matrix.md`, and `verification-summary.md`.
  </instructions>
  ```

- **description:** "speckit-echelon-verification (VERIFICATION): final backpropagation check"

speckit-echelon-verification (VERIFICATION) must:

1. Check every FR-*, AC-*, and NFR-* in `spec.md`.
2. Verify code, tests, integration evidence, and gate evidence.
3. Produce `gap-report.md`, `excess-report.md`, updated `traceability-matrix.md`, and `verification-summary.md`.

Handle result:

- **PASS** — continue to BUILD_DONE
- **FAIL** — create RW-* tasks, route through speckit-echelon-implementer (IMPLEMENTER) and quality gates, then re-run speckit-echelon-verification (VERIFICATION)

BUILD_DONE is forbidden while `verification-summary.md` is FAIL or `gap-report.md` contains open gaps.

**Specification Complete (mandatory on speckit-echelon-verification (VERIFICATION) PASS):**

1. Set `state.json.spec_status` to `"implemented"`.
2. Update `{spec_dir}/spec.md`: change `**Status**: In Progress` to `**Status**: Implemented`.
3. Confirm `state.json.build.tasks_completed_pct` is `100`. If not, recompute from `tasks.md`.
4. Log journal entry: `{ "type": "milestone", "event": "spec_implemented", "spec_id": "{spec_id}", "spec_dir": "{spec_dir}" }`.

### 8.2 Collect Reports

Verify all report files are populated:

- `spec-compliance-report.md` — One section per task
- `code-review-report.md` — One section per task
- `test-quality-report.md` — One section per task
- `integration-report.md` — One section per phase checkpoint + final
- `progress-report.md` — One section per task + summary
- `gap-report.md` — Verification coverage and gaps
- `verification-summary.md` — Final PASS / FAIL completion verdict

### 8.3 Update State

```json
{
  "status": "build_done",
  "phase": "build_done",
  "build": {
    "completed_tasks": "{total}",
    "verification_verdict": "PASS",
    "coverage_score": "100%",
    "current_task": null
  },
  "updated_at": "{ISO-8601}"
}
```

**Run History Write (mandatory at BUILD_DONE):**
1. Read `{spec_dir}/run-history.json` (must exist from Phase A run).
2. Append to `runs` array:
   ```json
   {
     "run_id": "{state.json.run_id}",
     "phase": "B",
     "status": "done",
     "verification_result": "{PASS|FAIL from verification-summary.md}",
     "spec_status": "{state.json.spec_status}",
     "timestamp": "{current UTC ISO-8601}"
   }
   ```
3. If `verification_result` is `"PASS"`: set `authoritative_run` to `"{state.json.run_id}"`.
4. Write the updated file.

### 8.4 Run speckit-echelon-scorekeeper (SCOREKEEPER)

After all build tasks complete, dispatch speckit-echelon-scorekeeper (SCOREKEEPER) to produce the build phase scorecard:

Use the Agent tool:

- **subagent_type:** `speckit-echelon-scorekeeper`
- **prompt:**

  ```xml
  <context>
  [include state.json, progress-report.md, all gate reports, reasoning-journal.jsonl, knowledge-base/agent-scores.yaml]
  </context>

  <instructions>
  You are SCOREKEEPER. Read agents/control/scorekeeper.md for your complete protocol.
  Score all build agents: speckit-echelon-implementer (IMPLEMENTER) (first-pass approvals vs rework), speckit-echelon-spec-guard (SPEC GUARD) (gaps caught vs missed by speckit-echelon-verification (VERIFICATION)), speckit-echelon-code-reviewer (CODE REVIEWER) (issues found), speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)) (coverage improvements). Collect peer appreciation from reasoning-journal.jsonl. Check badge criteria. Produce `agent-scorecard.md`. Update `knowledge-base/agent-scores.yaml`.
  </instructions>
  ```

- **description:** "speckit-echelon-scorekeeper (SCOREKEEPER): build phase scoring and badges"

Build-specific scoring:

```
Per task completed:
  speckit-echelon-implementer (IMPLEMENTER) first-pass approval: +3
  speckit-echelon-implementer (IMPLEMENTER) rework required: -1
  speckit-echelon-implementer (IMPLEMENTER) third rework: -3
  speckit-echelon-spec-guard (SPEC GUARD) caught gap: +3
  speckit-echelon-code-reviewer (CODE REVIEWER) found issue: +2
  speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)) improved coverage: +2

Per phase gate:
  speckit-echelon-integrator (INTEGRATOR) pass: +2
  speckit-echelon-visual-validator (VISUAL speckit-echelon-validator (VALIDATOR)) caught visual issue: +4

End of build:
  speckit-echelon-verification (VERIFICATION) 100% coverage: speckit-echelon-spec-guard (SPEC GUARD) gets +5 (Guardian Angel badge candidate)
  speckit-echelon-verification (VERIFICATION) found gaps: speckit-echelon-spec-guard (SPEC GUARD) gets -2 per gap (Blind Spot badge candidate)
```

---

## 8.5 Auto-Feedback & Post-Build Validation (Phase 5)

After speckit-echelon-scorekeeper (SCOREKEEPER) and before final summary, speckit-echelon-commander (COMMANDER) runs the autonomous feedback pipeline. This closes the learning loop without human input.

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.auto_feedback` (default: `true`). If `false`, skip to Section 8.6 Print Summary.

### 8.5.1 Dispatch speckit-echelon-auditor (AUDITOR) (Post-Build Self-Assessment)

Use the Agent tool:

- **subagent_type:** `speckit-echelon-auditor`
- **prompt:**

  ```xml
  <context>
  [include all build artifacts, spec artifacts, state.json, reasoning-journal.jsonl, knowledge-base/]
  </context>

  <instructions>
  You are AUDITOR. Read agents/learning/auditor.md for your complete protocol. Operate in **Mode 4: Post-Build Self-Assessment**.
  Compare squad predictions against build outcomes using build artifacts as ground truth. Read: estimates.md (predicted), state.json + progress-report.md (actual), plan.md + research.md (architecture decisions), spec.md + verification-summary.md + gap-report.md (requirements), risk-matrix.md + reasoning-journal.jsonl (risks), test-strategy.md + test-quality-report.md (tests).
  Produce `auto-feedback.yaml` and `feedback-report.md`. Flag any CRITICAL findings for speckit-echelon-commander (COMMANDER) triage.
  </instructions>
  ```

- **description:** "speckit-echelon-auditor (AUDITOR): post-build self-assessment — auto-feedback generation"

Context pack: all build artifacts + spec artifacts + state.json + reasoning-journal.jsonl + knowledge-base/

### 8.5.2 speckit-echelon-commander (COMMANDER) Triage of Critical Findings

Read `auto-feedback.yaml` → `critical_findings[]`. For each CRITICAL finding (max `feedback.max_expert_dispatches` from config, default 3):

| Finding Type | Expert Dispatched | Prompt Focus |
|---|---|---|
| `architecture_pivot` | speckit-echelon-investigator (INVESTIGATOR) + speckit-echelon-maverick (MAVERICK) | "Why was this ADR abandoned? What should the analysis have caught?" |
| `unpredicted_risk` | speckit-echelon-investigator (INVESTIGATOR) (+ speckit-echelon-guardian (GUARDIAN) if security) | "This risk was not predicted. Is it a known domain pattern?" |
| `effort_overrun` (ratio > 2.0) | speckit-echelon-realist (REALIST) | "Run reference class forecasting. What do similar tasks actually take?" |
| `requirements_gap` (missing > 3) | speckit-echelon-sage (SAGE) | "Why did Understanding miss these? Which metric should have caught them?" |
| `test_gap` | speckit-echelon-sentinel (SENTINEL) | "What coverage pattern would have caught these gaps?" |

For each expert dispatch:
1. Include the specific CRITICAL finding as context
2. Include relevant build artifacts
3. Expert produces investigation results
4. speckit-echelon-commander (COMMANDER) writes expert findings back into `auto-feedback.yaml` → `critical_findings[].expert_finding`

**Non-critical findings** (HIGH/MEDIUM/LOW/INFO): auto-update KB directly in Step 8.5.4 without expert dispatch.

### 8.5.3 Post-Build Validation (optional)

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.post_build_validation` (default: `true`). If `false`, skip to 8.5.4.

**a) Understanding re-scan:**

Dispatch speckit-echelon-sage (SAGE) in post-build-validation mode using the Agent tool:

- **subagent_type:** `speckit-echelon-sage`
- **prompt:**

  ```xml
  <context>
  [include spec.md, quality-gates.md from WHY3, auto-feedback.yaml, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **post-build-validation mode**.
  Run `speckit.echelon.understanding-validate` against the final `spec.md`. Compare scores against the last WHY3 `quality-gates.md`. If any category dropped > 0.05: flag as REGRESSION. If overall improved: log as IMPROVEMENT.
  Produce `post-build-validation.md`.
  </instructions>
  ```

- **description:** "speckit-echelon-sage (SAGE): post-build Understanding re-scan"

**b) Intent alignment check:**

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.post_build_intent_check` (default: `true`).

Dispatch speckit-echelon-tracker (TRACKER) in post-build-alignment mode using the Agent tool:

- **subagent_type:** `speckit-echelon-tracker`
- **prompt:**

  ```xml
  <context>
  [include user-intent.md, verification-summary.md, gap-report.md, implemented code, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **post-build-alignment mode**.
  Read `user-intent.md` (original user request) and the build output (verification-summary.md, gap-report.md, implemented code). Answer: "Does what was built match what the user asked for?" If MISALIGNED, describe the divergence.
  Produce `intent-alignment-final.md`.
  </instructions>
  ```

- **description:** "speckit-echelon-tracker (TRACKER): post-build intent alignment check"

**Drift Severity Gate (mandatory after speckit-echelon-tracker (TRACKER) produces `intent-alignment-final.md`):**

Read `drift_severity` from `intent-alignment-final.md`.

- **`ALIGNED`:** Log in `feedback-report.md` as INFO. Continue to BUILD_DONE.

- **`MINOR_DRIFT`:** Log in `feedback-report.md` as WARNING with the specific unmet intent points. Continue to BUILD_DONE. No correction dispatched.

- **`MAJOR_DRIFT` AND `autonomy_mode != "banzai"`:**
  1. Dispatch speckit-echelon-change-controller (CHANGE CONTROLLER) with the unmet intent points as the change description.
  2. speckit-echelon-change-controller (CHANGE CONTROLLER) assesses blast radius and creates RW-* rework tasks (max 1 rework pass — `state.json.rework_iteration_count` must be < 1 before entering this path; if already 1, log and continue without rework).
  3. speckit-echelon-engineering-manager (ENGINEERING MANAGER) executes the rework loop for the RW-* tasks.
  4. After rework: re-dispatch speckit-echelon-tracker (TRACKER) for a second alignment check. If still MAJOR_DRIFT after one rework pass, log as CRITICAL in `feedback-report.md` and continue — no infinite loop.

- **`MAJOR_DRIFT` AND `autonomy_mode == "banzai"`:**
  1. Set `state.json.requires_human_review` to `true`.
  2. Write `{spec_dir}/drift-escalation.md`:
     ```
     # Intent Drift Escalation
     **Run:** {state.json.run_id}
     **Severity:** MAJOR_DRIFT
     **Unmet intent points:** {list from intent-alignment-final.md}
     **Action required:** Human review needed before this spec can be marked complete.
     ```
  3. Log CRITICAL in `feedback-report.md`: `[speckit-echelon-commander (COMMANDER)] MAJOR_DRIFT detected in banzai mode — requires_human_review set. See drift-escalation.md.`
  4. Continue to BUILD_DONE (banzai no-checkpoint contract preserved).

### 8.5.4 Auto-Update Knowledge Base

After all expert investigations complete (or immediately for non-critical findings):

1. **calibration-profile.yaml:** Update domain accuracy based on effort ratio, architecture decisions, requirements coverage. Use KB Bootstrap Protocol.
2. **estimates-log.yaml:** Append per-task predicted vs actual effort entries.
3. **patterns.yaml:** Reinforce architecture decisions that held. Add caveats for decisions that broke.
4. **pitfalls.yaml:** Add entries for unpredicted risks and missing requirements patterns.

All writes go through `kb-write.sh append_entry` with locking.

### 8.5.5 Produce Final Feedback Summary

Append to `feedback-report.md`:

```markdown
## Auto-Feedback Summary

- Effort accuracy: {ratio}x ({severity})
- Architecture decisions held: {count}/{total}
- Requirements correct: {count}/{total}
- Risks predicted accurately: {count}/{total}
- Test coverage: {actual}% (planned: {planned}%)
- Critical findings: {count} ({count} investigated by experts)
- KB entries updated: {count}
- Post-build validation: {PASS|REGRESSION|N/A}
- Intent alignment: {ALIGNED|MISALIGNED|N/A}
```

---

### 8.6 Consolidation Phase — Constitution Amendment Candidates

Dispatch speckit-echelon-mirror (MIRROR) and speckit-echelon-veteran (VETERAN) in parallel to extract amendment candidates from this run's learnings.

**Dispatch speckit-echelon-mirror (MIRROR)** (`mode: "consolidation"`):

- Context pack: `feedback-report.md`, `intent-alignment-final.md`, `reasoning-journal.jsonl` (last 20 entries), `traceability-matrix.md`
- Output required: `amendment_candidates` list (may be empty)

**Dispatch speckit-echelon-veteran (VETERAN)** (`mode: "consolidation"`):

- Context pack: `{spec_dir}/run-history.json`, speckit-echelon-mirror (MIRROR)'s `amendment_candidates` (pass directly)
- Output required: `veteran_amendment_candidates` list (may be empty)

**speckit-echelon-commander (COMMANDER) consolidation (after both complete):**

1. Merge both candidate lists — deduplicate by principle text (exact or near-exact match).
2. Filter: keep only `confidence: high` or `confidence: medium` candidates.
3. If merged list is empty: skip the remaining steps. Set `state.json.constitution_amendments_pending` to `0`.
4. Write `{spec_dir}/constitution-amendment-candidates.md`:

   ```markdown
   # Constitution Amendment Candidates
   **Run:** {state.json.run_id}  **Spec:** {spec_id}  **Date:** {timestamp}

   Review each proposal and run `speckit.constitution` to apply approved ones.
   Reject by deleting the [PROPOSED] block.

   ---
   [PROPOSED: {principle text}]
   **Source:** {source from speckit-echelon-mirror (MIRROR)/speckit-echelon-veteran (VETERAN)}
   **Confidence:** {high|medium}
   **Category:** {category}
   ```

5. Append each candidate as a `[PROPOSED: ...]` block to `.specify/memory/constitution.md` (the existing file). Always append after the last existing section — never edit existing content.
6. Set `state.json.constitution_amendments_pending` to the count of candidates appended.
7. If `constitution_amendments_pending > 0`: add to the final run summary: `{N} constitution amendment candidate(s) pending human review — see {spec_dir}/constitution-amendment-candidates.md. Run speckit.constitution to approve or reject.`

**Important:** Always leave constitution promotion to humans. speckit-echelon-commander (COMMANDER) never auto-amends constitution content. Only humans can promote `[PROPOSED]` blocks to permanent principles via `speckit.constitution`. Human review is required.

---

### 8.7 Print Summary

Print the final build summary after BUILD_DONE. Always include quality gates, effort, auto-feedback, reports, agent scorecard, warnings, autonomous risk acceptances, and the HUMAN ACTIONS REQUIRED section.

For the complete summary template, load `workflow/phases/appendices/build-8-summary-reference.md`.

---

## 9. Error Handling

Retry transient task and review-agent timeouts once. Flag persistent task failures as BLOCKED or UNVALIDATED according to the gate. Pause when blockers accumulate or phase failures indicate bad task ordering.

For the complete task-level and phase-level handling table, load `workflow/phases/appendices/build-8-summary-reference.md`.

### Degraded Mode

Tasks or gates flagged as DEGRADED must include the degraded banner in their report section. Use `workflow/phases/appendices/build-8-summary-reference.md` for the exact banner.

---

## 10. Convergence Rules

Enforce the build phase convergence limits for gate fix cycles, IMPLEMENTER dispatches, blocked tasks, degraded tasks, token budget, and wall-clock time. Load `workflow/phases/appendices/build-8-summary-reference.md` for the exact limits.

---

## 11. Quick Reference: Build Flow

For the condensed build flow reference, load `workflow/phases/appendices/build-8-summary-reference.md`.

---

## 12. Harness Integration: Report Build Status

If the environment variable `HARNESS_BUILD_STATUS_FILE` is set, write the build outcome so the Python harness can detect success or impasse:

**On successful completion (BUILD_DONE reached):**

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  printf '{"status":"done"}' > "$HARNESS_BUILD_STATUS_FILE"
fi
```

**On unresolvable impasse (skill escalates after exhausting all retries):**

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  printf '{"status":"impasse","reason":"gate escalation after retries"}' > "$HARNESS_BUILD_STATUS_FILE"
fi
```

If `HARNESS_BUILD_STATUS_FILE` is not set (standalone invocation), skip this step entirely.
