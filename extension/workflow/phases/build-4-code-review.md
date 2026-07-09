# Phase: build-4-code-review
# Source: echelon.build.md §4 — Code Review Gate (CODE_REVIEW)
# Agent: speckit-echelon-code-reviewer (CODE REVIEWER)
# Read by: speckit-echelon-commander (COMMANDER) before each speckit-echelon-code-reviewer (CODE REVIEWER) dispatch

## 4. Code Review Gate (CODE_REVIEW)

### 4.1 Dispatch speckit-echelon-code-reviewer (CODE REVIEWER)

Use the Ralph-owned context pack:

- Read `build_slice_context_index_file` and use
  `agent_context_files.CODE_REVIEWER` as the prepared CODE REVIEWER context pack.
- Use only the named context pack and explicit verifier/build outputs already
  provided by Ralph.
- Do not compile a separate context pack by searching changed files,
  constitution, ADRs, or prior-task source patterns.

Use the Agent tool:

- **subagent_type:** `speckit-echelon-code-reviewer`
- **prompt:**

  ```xml
  <context>
  [include agent_context_files.CODE_REVIEWER from build_slice_context_index_file]
  </context>

  <instructions>
  You are CODE REVIEWER. Read agents/build/code-reviewer.md for your complete protocol.
  Review task {task_id} implementation.
  Append to `{spec_dir}/code-review-report.md`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-code-reviewer (CODE REVIEWER): {task_id} — quality review"

### 4.2 Handle Result

- **APPROVED** — Run `endocrine.sh on_gate_pass speckit-echelon-implementer (IMPLEMENTER)`. Proceed to speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)).
- **CHANGES_REQUESTED** — Run `endocrine.sh on_gate_fail speckit-echelon-implementer (IMPLEMENTER)` + `endocrine.sh on_rework speckit-echelon-implementer (IMPLEMENTER)`. Route back to speckit-echelon-implementer (IMPLEMENTER) with the specific issues. speckit-echelon-implementer (IMPLEMENTER) fixes and re-submits for review. Max 2 fix cycles. If still failing, flag as DEGRADED and proceed.
- **BLOCKED** — Run `endocrine.sh on_low_confidence speckit-echelon-implementer (IMPLEMENTER)`. Fundamental architectural issue. MANAGER decides: skip task, amend ADR, or escalate to human.
