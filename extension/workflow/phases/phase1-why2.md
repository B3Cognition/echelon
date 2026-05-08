# Phase: phase1-why2
# Source: echelon.run.md §5 — WHY2 Phase (Spec Validation)
# Agent: speckit-echelon-sage (SAGE) (mode: WHY2)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-sage (SAGE) WHY2

## 5. WHY2 Phase (Spec Validation)

### Preflight: Understanding Extension Availability (HARD STOP)

Before dispatching speckit-echelon-sage (SAGE) for WHY2 (and WHY3), speckit-echelon-commander (COMMANDER) MUST verify Understanding is available. speckit-echelon-sage (SAGE) invokes Understanding via the Skill tool (`speckit.echelon.understanding-validate`), not as a CLI binary.

If the `speckit.echelon.understanding-validate` skill invocation fails (Understanding extension unavailable):

1. Set `state.json.status` to `"blocked"`
2. Set `state.json.blocked_reason` to `"Understanding extension unavailable — required for WHY2/WHY3 spec validation"`
3. Print to terminal:

```
============================================
  SQUAD BLOCKED — UNDERSTANDING REQUIRED
============================================

Phase: WHY2 (spec-validation)
Required: Understanding extension (speckit.echelon.understanding-validate)

Heuristic fallback is NOT permitted.
Prior run (PAT-006) proved heuristic scoring is 15-29% overconfident,
producing misleading quality gates that corrupt calibration data.

Install: specify extension add understanding
============================================
```

4. **STOP execution.** Do not dispatch speckit-echelon-sage (SAGE). Do not proceed.

Persist `state.json.dependency_checks.understanding` with `status`, `checked_at`.

### Context Pack Assembly

Read and include in the subagent prompt:

- All current artifacts in `specs/{feature}/`
- Understanding access (via `speckit.echelon.understanding-validate` Skill tool)
- `calibration-profile.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include all current artifacts in specs/{feature}/, calibration-profile.yaml, reasoning-journal.json]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **spec-validation mode** (WHY2 — post-WHAT).
  Run Understanding `validate` against `spec.md` to get deterministic quality scores. After validation, also run per-requirement analysis with `--per-req --json --enhanced` and include the per-requirement failure list in issues.md for speckit-echelon-cartographer (CARTOGRAPHER) consumption. Challenge requirements for ambiguity, incompleteness, untestability. Hunt for missing edge cases, unstated assumptions, implicit requirements. Quality gates: overall >= 0.70, structure >= 0.70, testability >= 0.70, semantic >= 0.60, cognitive >= 0.60, readability >= 0.50, behavioral >= 0.50, depth >= 0.30. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-sage (SAGE) (WHY2): spec validation with Understanding quality gates + per-requirement analysis"

### Expected Outputs

- `issues.md` (scored findings: CRITICAL / HIGH / MEDIUM / LOW)
- `quality-gates.md` (Understanding metric results)

### Gate Check + Convergence

Read WHY2 outputs:

1. **Quality gates pass AND no CRITICAL issues** → proceed to ASSESS
2. **Quality gates fail OR CRITICAL issues found** → route back to WHAT with specific amendment demands. Include the per-requirement failure list from issues.md "Per-Requirement Failures" section in speckit-echelon-cartographer (CARTOGRAPHER)'s context pack so speckit-echelon-cartographer (CARTOGRAPHER) knows which specific requirements to amend and which categories are failing. Increment iteration. Check limits.
3. **Track quality scores** — append to `state.json.quality_scores[]` an object with ALL of these fields: `pass` (iteration label), `overall`, `structure`, `readability`, `cognitive`, `semantic`, `testability`, `behavioral`, `depth`. All score values come from Understanding output (quality-gates.md). If a category score is not available, set to `null`.
4. **Convergence check:** If this is iteration >= 2, compare quality scores across ALL 7 categories: compute the absolute delta for EACH category between the last two WHY passes. Convergence is met when MAX(abs(delta)) across all 7 categories is < `convergence_delta` (per `echelon-config.yml convergence:`) for 2 consecutive passes. This prevents false convergence where overall is stable but individual categories oscillate.
   - Same issue appears 3x → defer or escalate (see Section 15)

**Transition:** `phases[phase2-decide]` — see `workflow/definition.yaml`
