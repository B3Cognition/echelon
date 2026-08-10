# Phase: build-5-test-guard
# Source: echelon.build.md §5 — Test Guardian Gate (TEST_GUARD)
# Agent: echelon.test-guardian (TEST echelon.guardian (GUARDIAN))
# Read by: echelon.commander (COMMANDER) before each echelon.test-guardian (TEST echelon.guardian (GUARDIAN)) dispatch

## 5. Test Guardian Gate (TEST_GUARD)

### 5.1 Dispatch echelon.test-guardian (TEST echelon.guardian (GUARDIAN))

Use the Ralph-owned context pack:

- Read `build_slice_context_index_file` and use
  `agent_context_files.TEST_GUARDIAN` as the prepared TEST GUARDIAN context pack.
- Use only the named context pack and explicit verifier/build outputs already
  provided by Ralph.
- Do not compile a separate context pack by searching source files, test files,
  task acceptance criteria, test strategy, or coverage artifacts.

Use the Agent tool:

- **subagent_type:** `echelon.test-guardian`
- **prompt:**

  ```xml
  <context>
  [include agent_context_files.TEST_GUARDIAN from build_slice_context_index_file]
  </context>

  <instructions>
  You are TEST GUARDIAN. Read subagents/echelon.test-guardian.md for your complete protocol.
  Validate test quality for task {task_id}.
  Append to `{spec_dir}/test-quality-report.md`. Update `coverage-map.md`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon.test-guardian (TEST echelon.guardian (GUARDIAN)): {task_id} — test quality validation"

### 5.2 Handle Result

- **PASS** — Run `endocrine.sh on_gate_pass echelon.implementer (IMPLEMENTER)`. Task complete. Proceed to echelon.progress-tracker (PROGRESS echelon.tracker (TRACKER)).
- **FAIL** — Run `endocrine.sh on_gate_fail echelon.implementer (IMPLEMENTER)` + `endocrine.sh on_rework echelon.implementer (IMPLEMENTER)`. Route back to echelon.implementer (IMPLEMENTER) to add missing tests. Max 2 fix cycles. If still failing, flag as DEGRADED and proceed.
- **WARN** — Task complete with noted improvements. Proceed to echelon.progress-tracker (PROGRESS echelon.tracker (TRACKER)).
