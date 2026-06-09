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

### 8.1c.1 Intent Drift Gate

Before BUILD_DONE, run the post-build TRACKER intent alignment check from
`workflow/phases/appendices/build-8-feedback-reference.md` and read
`drift_severity` from `intent-alignment-final.md`.

- `ALIGNED` / `MINOR_DRIFT`: record the result in `feedback-report.md`.
- `MAJOR_DRIFT`: dispatch speckit-echelon-change-controller (CHANGE CONTROLLER)
  for one bounded rework pass unless `autonomy_mode == "banzai"`.
- `MAJOR_DRIFT` in `banzai`: return `requires_human_review: true` and write
  `drift-escalation.md`.

**Specification Complete (mandatory on speckit-echelon-verification (VERIFICATION) PASS):**

1. Validate task progress integrity with `python -m harness validate-task-progress "{spec_dir}/tasks.md" "{state_json_path}"`.
2. Confirm `state.json.build.tasks_completed_pct` is `100`. If not, recompute from canonical checked task rows in `tasks.md` and return the full updated `build` object in `echelon_result.state_updates`.
3. If progress validation fails, do not enter BUILD_DONE. Fix canonical task row checkboxes, `**Status:**` lines, and the returned `build` state update first.
4. Return this journal entry in `echelon_result.journal_entries`: `{ "type": "milestone", "event": "spec_implemented", "spec_id": "{spec_id}", "spec_dir": "{spec_dir}" }`.

### 8.2 Collect Reports

Verify all report files are populated:

- `spec-compliance-report.md` — One section per task
- `code-review-report.md` — One section per task
- `test-quality-report.md` — One section per task
- `integration-report.md` — One section per phase checkpoint + final
- `progress-report.md` — One section per task + summary
- `gap-report.md` — Verification coverage and gaps
- `verification-summary.md` — Final PASS / FAIL completion verdict

### 8.3 Return Build Completion State

Return these state updates in `echelon_result`; the harness applies them to `${SQUAD_DIR}/state.json`.
Because `build` is a top-level object, include the full updated `build` object and preserve existing fields.

```yaml
echelon_result:
  state_updates:
    status: build_done
    phase: build_done
    build:
      total_tasks: <existing total_tasks>
      completed_tasks: "{total}"
      tasks_completed_pct: 100
      verification_verdict: PASS
      coverage_score: "100%"
      current_task: null
      current_phase_group: null
      task_results: <existing task_results>
      phase_checkpoints: <existing phase_checkpoints>
    updated_at: "{ISO-8601}"
```

**Run History Ownership:**

Do not edit `{spec_dir}/run-history.json` in this phase. Ralph writes the
authoritative Phase B implementation run after build, verify, task progress
integrity, fulfillment, commit, and publish all converge.

### 8.3b Run speckit-echelon-consolidator (CONSOLIDATOR)

After the implementation is verified and before speckit-echelon-scorekeeper (SCOREKEEPER), dispatch speckit-echelon-consolidator (CONSOLIDATOR) in `offline_consolidation` mode so build-phase lessons become reusable schemas.

Use the Agent tool:

- **subagent_type:** `speckit-echelon-consolidator`
- **prompt:**

  ```xml
  <context>
  [include state.json, tasks.md, spec.md, progress-report.md, integration-report.md, verification-summary.md, gap-report.md, reasoning-journal.jsonl, knowledge-base/patterns.yaml, knowledge-base/pitfalls.yaml, knowledge-base/calibration-profile.yaml, extension/templates/schema-consolidation-template.md]
  </context>

  <instructions>
  You are CONSOLIDATOR. Read agents/learning/consolidator.md for your complete protocol.
  Run offline consolidation for this build. Promote repeated implementation lessons into schemas, reinforce or decay existing schemas, mark consolidated traces, and produce `{spec_dir}/patterns/schema-consolidation.md` using the provided template. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-consolidator (CONSOLIDATOR): build-phase schema consolidation before scoring"

If speckit-echelon-consolidator (CONSOLIDATOR) is unavailable, record a warning and continue to speckit-echelon-scorekeeper (SCOREKEEPER). Do not block BUILD_DONE on consolidation availability.

### 8.4 Run speckit-echelon-scorekeeper (SCOREKEEPER)

After all build tasks complete, dispatch speckit-echelon-scorekeeper (SCOREKEEPER) to produce the build phase scorecard:

Use the Agent tool:

- **subagent_type:** `speckit-echelon-scorekeeper`
- **prompt:**

  ```xml
  <context>
  [include state.json, progress-report.md, all gate reports, reasoning-journal.jsonl, knowledge-base/agent-scores.yaml, agents/control/appendices/scorekeeper-output-template.md, agents/control/appendices/scorekeeper-scoring-reference.md]
  </context>

  <instructions>
  You are SCOREKEEPER. Read agents/control/scorekeeper.md for your complete protocol.
  Score all build agents: speckit-echelon-implementer (IMPLEMENTER) (first-pass approvals vs rework), speckit-echelon-spec-guard (SPEC GUARD) (gaps caught vs missed by speckit-echelon-verification (VERIFICATION)), speckit-echelon-code-reviewer (CODE REVIEWER) (issues found), speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)) (coverage improvements). Collect peer appreciation from reasoning-journal.jsonl. Check badge criteria. Produce `agent-scorecard.md` using the provided template. Update `knowledge-base/agent-scores.yaml`.
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

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.auto_feedback` (default: `true`). If `false`, skip to Section 8.7 Print Summary.

Load `workflow/phases/appendices/build-8-feedback-reference.md` before running auto-feedback. It contains:

1. AUDITOR post-build self-assessment dispatch.
2. Critical finding triage and expert dispatch matrix.
3. Optional post-build Understanding re-scan.
4. Optional final intent alignment check and drift severity gate.
5. Knowledge-base update rules.
6. Final feedback summary template.

---

### 8.6 Consolidation Phase — Constitution Amendment Candidates

Load `workflow/phases/appendices/build-8-feedback-reference.md` and run its Consolidation Phase. Always leave constitution promotion to humans. speckit-echelon-commander (COMMANDER) never auto-amends constitution content.

---

### 8.7 Print Summary

Before printing the final build summary, refresh the human artifact map deterministically:

```bash
echelon artifacts "${SPEC_ID}"
```

ALWAYS use `echelon artifacts` to generate `{spec_dir}/ARTIFACTS.md` after build finalization. NEVER hand-author `ARTIFACTS.md`; it is Python-owned and overwritten on regeneration.

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

If the environment variable `HARNESS_BUILD_STATUS_FILE` is set, write the build outcome so the Python harness can detect whether this invocation completed cleanly:

**On useful verified progress, even when the overall spec remains incomplete:**

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  printf '{"status":"done","reason":"completed verified build iteration"}' > "$HARNESS_BUILD_STATUS_FILE"
fi
```

**On a real external blocker that prevents further implementation progress:**

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  printf '{"status":"blocked","reason":"specific blocker requiring human input"}' > "$HARNESS_BUILD_STATUS_FILE"
fi
```

Do not write `impasse` for ordinary partial progress. An incomplete MVP is not a blocker by itself.

If `HARNESS_BUILD_STATUS_FILE` is not set (standalone invocation), skip this step entirely.
