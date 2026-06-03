# Phase: build-5-test-guard
# Source: echelon.build.md §5 — Test Guardian Gate (TEST_GUARD)
# Agent: speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN))
# Read by: speckit-echelon-commander (COMMANDER) before each speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)) dispatch

## 5. Test Guardian Gate (TEST_GUARD)

### 5.1 Dispatch speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN))

Compile context pack:

- Test files from speckit-echelon-implementer (IMPLEMENTER)
- Source files from speckit-echelon-implementer (IMPLEMENTER)
- Task acceptance criteria
- Relevant section of `test-strategy.md`
- `coverage-map.md`

Use the Agent tool:

- **subagent_type:** `speckit-echelon-test-guardian`
- **prompt:**

  ```xml
  <context>
  [include files listed above]
  </context>

  <instructions>
  You are TEST GUARDIAN. Read agents/build/test-guardian.md for your complete protocol.
  Validate test quality for task {task_id}.
  Append to `{spec_dir}/test-quality-report.md`. Update `coverage-map.md`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)): {task_id} — test quality validation"

### 5.2 Handle Result

- **PASS** — Run `endocrine.sh on_gate_pass speckit-echelon-implementer (IMPLEMENTER)`. Task complete. Proceed to speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)).
- **FAIL** — Run `endocrine.sh on_gate_fail speckit-echelon-implementer (IMPLEMENTER)` + `endocrine.sh on_rework speckit-echelon-implementer (IMPLEMENTER)`. Route back to speckit-echelon-implementer (IMPLEMENTER) to add missing tests. Max 2 fix cycles. If still failing, flag as DEGRADED and proceed.
- **WARN** — Task complete with noted improvements. Proceed to speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)).
