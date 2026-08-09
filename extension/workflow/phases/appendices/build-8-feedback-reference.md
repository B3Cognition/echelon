# build-8-finalize Feedback Reference

Long-form reference for `workflow/phases/build-8-finalize.md` post-build feedback, validation, and consolidation steps.

## Template Contract

Use these templates for run-local feedback and escalation artifacts:

- `extension/templates/feedback-report-template.md` for `feedback-report.md`
- `extension/templates/drift-escalation-template.md` for `drift-escalation.md`
- `extension/templates/constitution-amendment-candidates-template.md` for `constitution-amendment-candidates.md`

## Auto-Feedback Pipeline

After echelon-scorekeeper (SCOREKEEPER) and before final summary, echelon-commander (COMMANDER) runs the autonomous feedback pipeline. This closes the learning loop without human input.

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.auto_feedback` (default: `true`). If `false`, skip post-build feedback and continue to final summary.

### Dispatch echelon-auditor (AUDITOR)

Use the Agent tool:

- **subagent_type:** `echelon-auditor`
- **prompt:**

  ```xml
  <context>
  [include all build artifacts, spec artifacts, state.json, reasoning-journal.jsonl, knowledge-base/, extension/templates/feedback-report-template.md]
  </context>

  <instructions>
  You are AUDITOR. Read agents/learning/auditor.md for your complete protocol. Operate in **Mode 4: Post-Build Self-Assessment**.
  Compare squad predictions against build outcomes using build artifacts as ground truth. Read: estimates.md (predicted), state.json + progress-report.md (actual), plan.md + research.md (architecture decisions), spec.md + verification-summary.md + gap-report.md (requirements), risk-matrix.md + reasoning-journal.jsonl (risks), test-strategy.md + test-quality-report.md (tests).
  Produce `auto-feedback.yaml` and `feedback-report.md` using the provided feedback report template. Flag any CRITICAL findings for echelon-commander (COMMANDER) triage.
  </instructions>
  ```

- **description:** "echelon-auditor (AUDITOR): post-build self-assessment - auto-feedback generation"

Context pack: all build artifacts + spec artifacts + state.json + reasoning-journal.jsonl + knowledge-base/

### Critical Finding Triage

Read `auto-feedback.yaml` -> `critical_findings[]`. For each CRITICAL finding, cap expert dispatches at `feedback.max_expert_dispatches` from config, default 3.

| Finding Type | Expert Dispatched | Prompt Focus |
|---|---|---|
| `architecture_pivot` | echelon-investigator (INVESTIGATOR) + echelon-maverick (MAVERICK) | "Why was this ADR abandoned? What should the analysis have caught?" |
| `unpredicted_risk` | echelon-investigator (INVESTIGATOR) (+ echelon-guardian (GUARDIAN) if security) | "This risk was not predicted. Is it a known domain pattern?" |
| `effort_overrun` (ratio > 2.0) | echelon-realist (REALIST) | "Run reference class forecasting. What do similar tasks actually take?" |
| `requirements_gap` (missing > 3) | echelon-sage (SAGE) | "Why did Understanding miss these? Which metric should have caught them?" |
| `test_gap` | echelon-sentinel (SENTINEL) | "What coverage pattern would have caught these gaps?" |

For each expert dispatch:

1. Include the specific CRITICAL finding as context.
2. Include relevant build artifacts.
3. Expert produces investigation results.
4. echelon-commander (COMMANDER) writes expert findings back into `auto-feedback.yaml` -> `critical_findings[].expert_finding`.

**Non-critical findings** (HIGH/MEDIUM/LOW/INFO): auto-update KB directly without expert dispatch.

## Post-Build Validation

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.post_build_validation` (default: `true`). If `false`, skip this section.

### Understanding Re-Scan

Dispatch echelon-sage (SAGE) in post-build-validation mode using the Agent tool:

- **subagent_type:** `echelon-sage`
- **prompt:**

  ```xml
  <context>
  [include spec.md, quality-gates.md from WHY3, auto-feedback.yaml, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **post-build-validation mode**.
  Run `echelon.understanding-validate` against the final `spec.md`. Compare scores against the last WHY3 `quality-gates.md`. If any category dropped > 0.05: flag as REGRESSION. If overall improved: log as IMPROVEMENT.
  Produce `post-build-validation.md`.
  </instructions>
  ```

- **description:** "echelon-sage (SAGE): post-build Understanding re-scan"

### Intent Alignment Check

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.post_build_intent_check` (default: `true`).

Dispatch echelon-tracker (TRACKER) in post-build-alignment mode using the Agent tool:

- **subagent_type:** `echelon-tracker`
- **prompt:**

  ```xml
  <context>
  [include user-intent.md, verification-summary.md, gap-report.md, implemented code, extension/templates/intent-alignment-final-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **post-build-alignment mode**.
  Read `user-intent.md` (original user request) and the build output (verification-summary.md, gap-report.md, implemented code). Answer: "Does what was built match what the user asked for?" If MISALIGNED, describe the divergence.
  Produce `intent-alignment-final.md` using the provided template.
  </instructions>
  ```

- **description:** "echelon-tracker (TRACKER): post-build intent alignment check"

### Drift Severity Gate

Read `drift_severity` from `intent-alignment-final.md`.

- **`ALIGNED`:** Log in `feedback-report.md` as INFO. Continue to BUILD_DONE.
- **`MINOR_DRIFT`:** Log in `feedback-report.md` as WARNING with the specific unmet intent points. Continue to BUILD_DONE. No correction dispatched.
- **`MAJOR_DRIFT` AND `autonomy_mode != "banzai"`:**
  1. Dispatch echelon-change-controller (CHANGE CONTROLLER) with the unmet intent points as the change description.
  2. echelon-change-controller (CHANGE CONTROLLER) assesses blast radius and creates RW-* rework tasks. Max one rework pass: `state.json.rework_iteration_count` must be < 1 before entering this path. If already 1, log and continue without rework.
  3. echelon-engineering-manager (ENGINEERING MANAGER) executes the rework loop for the RW-* tasks.
  4. After rework: re-dispatch echelon-tracker (TRACKER) for a second alignment check. If still MAJOR_DRIFT after one rework pass, log as CRITICAL in `feedback-report.md` and continue. Do not enter an infinite loop.
- **`MAJOR_DRIFT` AND `autonomy_mode == "banzai"`:**
  1. Return `requires_human_review: true` in `echelon_result.state_updates`.
  2. Write `{spec_dir}/drift-escalation.md` using `extension/templates/drift-escalation-template.md`, populated from `intent-alignment-final.md` and `state.json`.

  3. Log CRITICAL in `feedback-report.md`: `[echelon-commander (COMMANDER)] MAJOR_DRIFT detected in banzai mode - requires_human_review returned. See drift-escalation.md.`
  4. Continue to BUILD_DONE.

## Auto-Update Knowledge Base

After all expert investigations complete, or immediately for non-critical findings:

1. **calibration-profile.yaml:** Update domain accuracy based on effort ratio, architecture decisions, requirements coverage. Use KB Bootstrap Protocol.
2. **estimates-log.yaml:** Append per-task predicted vs actual effort entries.
3. **patterns.yaml:** Reinforce architecture decisions that held. Add caveats for decisions that broke.
4. **pitfalls.yaml:** Add entries for unpredicted risks and missing requirements patterns.

All writes go through `kb-write.sh append_entry` with locking.

## Final Feedback Summary

Append the following data to the `## Auto-Feedback Summary` section of `feedback-report.md` from `extension/templates/feedback-report-template.md`:

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

## Consolidation Phase - Constitution Amendment Candidates

Dispatch echelon-mirror (MIRROR) and echelon-veteran (VETERAN) in parallel to extract amendment candidates from this run's learnings.

**Dispatch echelon-mirror (MIRROR)** (`mode: "consolidation"`):

- Context pack: `feedback-report.md`, `intent-alignment-final.md`, `reasoning-journal.jsonl` (last 20 entries), `traceability-matrix.md`
- Output required: `amendment_candidates` list (may be empty)

**Dispatch echelon-veteran (VETERAN)** (`mode: "consolidation"`):

- Context pack: `{spec_dir}/run-history.json`, echelon-mirror (MIRROR)'s `amendment_candidates` (pass directly)
- Output required: `veteran_amendment_candidates` list (may be empty)

**echelon-commander (COMMANDER) consolidation (after both complete):**

1. Merge both candidate lists. Deduplicate by principle text, exact or near-exact match.
2. Filter: keep only `confidence: high` or `confidence: medium` candidates.
3. If merged list is empty: skip the remaining steps. Return `constitution_amendments_pending: 0` in `echelon_result.state_updates`.
4. Write `{spec_dir}/constitution-amendment-candidates.md` using `extension/templates/constitution-amendment-candidates-template.md`. Preserve each `[PROPOSED: ...]` block in its candidate detail, source, confidence, category, and human decision request.

5. Do not append candidates to `.specify/memory/constitution.md` or otherwise modify the canonical constitution. Leave every proposal in `constitution-amendment-candidates.md` for CHIEF and human review through `speckit.constitution`.
6. Return `constitution_amendments_pending: <count>` in `echelon_result.state_updates`.
7. If `constitution_amendments_pending > 0`: add to the final run summary: `{N} constitution amendment candidate(s) pending human review - see {spec_dir}/constitution-amendment-candidates.md. Run speckit.constitution to approve or reject.`

Always leave constitution promotion to humans. echelon-commander (COMMANDER) never auto-amends constitution content.
