# Phase: build-3-spec-guard
# Source: echelon.build.md §3 — Spec Guard Gate (SPEC_GUARD)
# Agent: echelon-spec-guard (SPEC GUARD)
# Read by: echelon-commander (COMMANDER) before each echelon-spec-guard (SPEC GUARD) dispatch

## 3. Spec Guard Gate (SPEC_GUARD)

### 3.1 Dispatch echelon-spec-guard (SPEC GUARD)

Use the Ralph-owned context pack:

- Read `build_slice_context_index_file` and use
  `agent_context_files.SPEC_GUARD` as the prepared SPEC GUARD context pack.
- Use only the named context pack and explicit verifier/build outputs already
  provided by Ralph.
- Do not compile a separate context pack by searching changed files, task rows,
  requirements, or `spec.md`.

Use the Agent tool:

- **subagent_type:** `echelon-spec-guard`
- **prompt:**

  ```xml
  <context>
  [include agent_context_files.SPEC_GUARD from build_slice_context_index_file]
  </context>

  <instructions>
  You are SPEC GUARD. Read agents/build/spec-guard.md for your complete protocol.
  Verify task {task_id} implementation against spec requirements.
  Append to `{spec_dir}/spec-compliance-report.md`. Update `{spec_dir}/traceability-matrix.md`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon-spec-guard (SPEC GUARD): {task_id} — spec compliance check"

### 3.2 Handle Result

- **PASS** — Run `endocrine.sh on_gate_pass echelon-implementer (IMPLEMENTER)`. Proceed to echelon-code-reviewer (CODE REVIEWER).
- **FAIL** — Run `endocrine.sh on_gate_fail echelon-implementer (IMPLEMENTER)` + `endocrine.sh on_rework echelon-implementer (IMPLEMENTER)`. Route back to echelon-implementer (IMPLEMENTER) with the specific gaps. echelon-implementer (IMPLEMENTER) fixes and re-submits. Max 2 fix cycles per gate. If still failing after 2 cycles, flag as DEGRADED and proceed.
- **WARN** — Always log warnings and proceed to echelon-code-reviewer (CODE REVIEWER); warnings do not block.

### On Non-Obvious FAIL

If echelon-spec-guard (SPEC GUARD) or echelon-code-reviewer (CODE REVIEWER) returns FAIL and the issue is non-obvious (logic error, integration issue, not just missing test or style):

1. Dispatch echelon-debugger (DEBUGGER) instead of sending directly back to echelon-implementer (IMPLEMENTER)
2. echelon-debugger (DEBUGGER): reproduce → isolate → root cause → fix → verify
3. If root cause is within task scope → echelon-debugger (DEBUGGER) fixes
4. If root cause requires architecture change → MANAGER routes to HOW
5. If root cause requires spec change → MANAGER routes to WHAT
