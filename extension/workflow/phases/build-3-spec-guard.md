# Phase: build-3-spec-guard
# Source: echelon.build.md §3 — Spec Guard Gate (SPEC_GUARD)
# Agent: speckit-echelon-spec-guard (SPEC GUARD)
# Read by: speckit-echelon-commander (COMMANDER) before each speckit-echelon-spec-guard (SPEC GUARD) dispatch

## 3. Spec Guard Gate (SPEC_GUARD)

### 3.1 Dispatch speckit-echelon-spec-guard (SPEC GUARD)

Compile context pack:

- Files changed by speckit-echelon-implementer (IMPLEMENTER)
- The task definition (acceptance criteria, FR-* references)
- Referenced FR-* requirements from `spec.md`
- Full `spec.md` for cross-reference

Use the Agent tool:

- **subagent_type:** `speckit-echelon-spec-guard`
- **prompt:**

  ```xml
  <context>
  [include files listed above]
  </context>

  <instructions>
  You are SPEC GUARD. Read agents/build/spec-guard.md for your complete protocol.
  Verify task {task_id} implementation against spec requirements.
  Append to `{spec_dir}/spec-compliance-report.md`. Update `{spec_dir}/traceability-matrix.md`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-spec-guard (SPEC GUARD): {task_id} — spec compliance check"

### 3.2 Handle Result

- **PASS** — Run `endocrine.sh on_gate_pass speckit-echelon-implementer (IMPLEMENTER)`. Proceed to speckit-echelon-code-reviewer (CODE REVIEWER).
- **FAIL** — Run `endocrine.sh on_gate_fail speckit-echelon-implementer (IMPLEMENTER)` + `endocrine.sh on_rework speckit-echelon-implementer (IMPLEMENTER)`. Route back to speckit-echelon-implementer (IMPLEMENTER) with the specific gaps. speckit-echelon-implementer (IMPLEMENTER) fixes and re-submits. Max 2 fix cycles per gate. If still failing after 2 cycles, flag as DEGRADED and proceed.
- **WARN** — Always log warnings and proceed to speckit-echelon-code-reviewer (CODE REVIEWER); warnings do not block.

### On Non-Obvious FAIL

If speckit-echelon-spec-guard (SPEC GUARD) or speckit-echelon-code-reviewer (CODE REVIEWER) returns FAIL and the issue is non-obvious (logic error, integration issue, not just missing test or style):

1. Dispatch speckit-echelon-debugger (DEBUGGER) instead of sending directly back to speckit-echelon-implementer (IMPLEMENTER)
2. speckit-echelon-debugger (DEBUGGER): reproduce → isolate → root cause → fix → verify
3. If root cause is within task scope → speckit-echelon-debugger (DEBUGGER) fixes
4. If root cause requires architecture change → MANAGER routes to HOW
5. If root cause requires spec change → MANAGER routes to WHAT
