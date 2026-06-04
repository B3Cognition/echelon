# Phase: phase1-why2
# Source: echelon.run.md §5 — WHY2 Phase (Spec Validation)
# Agent: speckit-echelon-sage (SAGE) (mode: WHY2)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-sage (SAGE) WHY2

## 5. WHY2 Phase (Spec Validation)

### Preflight: Understanding Extension Availability (HARD STOP)

Before dispatching speckit-echelon-sage (SAGE) for WHY2 (and WHY3), speckit-echelon-commander (COMMANDER) MUST verify Understanding is available. speckit-echelon-sage (SAGE) invokes Understanding via the Skill tool (`speckit.echelon.understanding-validate`), not as a CLI binary.

If the `speckit.echelon.understanding-validate` skill invocation fails (Understanding extension unavailable):

1. Return the blocked status in `echelon_result.state_updates`:

   ```yaml
   status: blocked
   blocked_reason: "Understanding extension unavailable — required for WHY2/WHY3 spec validation"
   dependency_checks:
     understanding:
       status: unavailable
       checked_at: "<ISO-8601>"
       version: null
   ```

2. Print to terminal:

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

3. **STOP execution.** Always stop at the BLOCKED banner. Do not dispatch speckit-echelon-sage (SAGE). Do not proceed.

**MANDATORY — return the Understanding availability check result in `echelon_result.state_updates` before dispatching speckit-echelon-sage (SAGE):**

```yaml
dependency_checks:
  understanding:
    status: available
    checked_at: "<ISO-8601>"
    version: "<version string from skill output if available, else null>"
```

If other dependency checks already exist, include the full existing `dependency_checks` object plus the updated `understanding` entry because harness state updates are shallow top-level merges.

If the skill is unavailable, always return `dependency_checks.understanding.status: unavailable` and HARD STOP per the BLOCKED banner above — do not skip this state update and continue.

### Context Pack Assembly

Read and include in the subagent prompt:

- All current artifacts in `{spec_dir}/`
- Understanding access (via `speckit.echelon.understanding-validate` Skill tool)
- `agents/exploration/templates/sage-quality-gates-template.md`
- `agents/exploration/templates/sage-issues-template.md`
- `calibration-profile.yaml`
- `reasoning-journal.jsonl`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include all current artifacts in {spec_dir}/, sage WHY2 output templates, calibration-profile.yaml, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **spec-validation mode** (WHY2 — post-WHAT).
  Run Understanding `validate` against `spec.md` to get deterministic quality scores. After validation, also run per-requirement analysis with `--per-req --json --enhanced` and include the per-requirement failure list in issues.md for speckit-echelon-cartographer (CARTOGRAPHER) consumption. Challenge requirements for ambiguity, incompleteness, untestability. Hunt for missing edge cases, unstated assumptions, implicit requirements. Quality gates: overall >= 0.70, structure >= 0.70, testability >= 0.70, semantic >= 0.60, cognitive >= 0.60, readability >= 0.50, behavioral >= 0.50, depth >= 0.30. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
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
3. **Track quality scores — MANDATORY return on every WHY2 pass (pass or fail):** include the full updated `quality_scores` list in `echelon_result.state_updates`, appending an object with **every** field below. Missing a field breaks the convergence delta check in step 4.

   ```yaml
   quality_scores:
     - pass: "WHY2-iter-{N}"
       overall: <float|null>
       structure: <float|null>
       readability: <float|null>
       cognitive: <float|null>
       semantic: <float|null>
       testability: <float|null>
       behavioral: <float|null>
       depth: <float|null>
   ```

   All score values come from Understanding output (quality-gates.md). Use `null` only when Understanding genuinely did not return that category (e.g., spec has zero requirements). Always include the prior series plus the new entry, even on FAIL — do not skip it because convergence depends on the full series and harness state updates are shallow top-level merges.
4. **Convergence check:** If this is iteration >= 2, compare quality scores across ALL 7 categories: compute the absolute delta for EACH category between the last two WHY passes. Convergence is met when MAX(abs(delta)) across all 7 categories is < `convergence_delta` (per `echelon-config.yml convergence:`) for 2 consecutive passes. This prevents false convergence where overall is stable but individual categories oscillate.
   - Same issue appears 3x → defer or escalate (see Section 15)

### WHY2 iteration stop conditions

COMMANDER evaluates these in priority order after each WHY2 pass. Execute the **first matching condition** and stop evaluating further.

| Priority | Condition | Transition | State updates to return |
|---|---|---|---|
| 1 | `iteration >= max_squad_iterations` (from `echelon-config.yml convergence:`) | → phase2-decide | `convergence_forced: true`, `convergence_reason: "max_iterations_reached"` |
| 2 | `token_usage >= token_budget_k * 1000` (from `echelon-config.yml budget:`) | → phase2-decide | `convergence_forced: true`, `convergence_reason: "token_budget_exhausted"` |
| 3 | `iteration >= 4` AND cumulative improvement in `overall` score (iteration 1 → now) < `0.05` | → phase2-decide | `convergence_forced: true`, `convergence_reason: "hard_plateau"` |
| 4 | MAX(abs(delta)) across all 7 score categories < `convergence_delta` for 2 consecutive passes | → phase2-decide | `convergence_detected: true`, `convergence_reason: "delta_converged"` |
| 5 | Quality gates pass AND no CRITICAL issues | → phase2-decide | `convergence_detected: true` |
| 6 | All other cases (gates fail or CRITICAL issues present) | → phase1-what (increment iteration) | — |

When transitioning on conditions 1–3 (`convergence_forced: true`), write a quality report noting what was not completed and why, and flag artifacts as "forced convergence."

**Transition:** `phases[phase2-decide]` — see `workflow/definition.yaml`

### User-gated CRITICAL issues

When CRITICAL issues are **user-gated** — they require information only the user holds
(legal rights, product positioning decisions, audience policy, cost envelope) and cannot
be resolved by any squad agent — include in `echelon_result.state_updates`:

```yaml
escalation_question: |
  Q1: <compact blocking question — one line, state the stakes>
  Q2: <compact blocking question>
blocked_reason: |
  WHY2: CRITICAL user-gated issues — squad-internal iteration cannot substitute for user input
```

**Criteria — ALL must be true to set escalation_question:**

1. Cannot be resolved by any squad agent (DISCOVER, SYNTHESIZER, MODELER, TRACKER, INVESTIGATOR)
2. Requires information only the user holds (legal rights, positioning decisions, audience policy)
3. Proceeding without it requires an arbitrary coin-flip that binds all downstream phases

**Always route squad-solvable CRITICAL issues back to DISCOVER. Do NOT set escalation_question for them** (missing boundaries,
glossary gaps, unread manual pages, contradictions resolvable by ORACLE/INVESTIGATOR).
Those keep routing to DISCOVER as normal.

The harness reads `escalation_question` and either:

- **banzai mode** → dispatches COMMANDER for best-judgment answers, run continues
- **semi/guided mode** → stops the run; user answers via `echelon resume "<answers>"`
