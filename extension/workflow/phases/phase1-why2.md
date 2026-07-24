# Phase: phase1-why2
# Agent: speckit-echelon-sage (SAGE), mode WHY2

## Purpose

Interpret controller-certified Understanding evidence and perform the first
qualitative adversarial review of the specification. Deterministic analysis has
already completed in `phase1-understanding` before this provider dispatch.

## Certified Precondition

The harness injects a **Certified Understanding Evidence** section containing
the immutable report path, digest, iteration, aggregate pass value, and failing
gates. SAGE must read that report and must not run validators, discover quality
configuration, recalculate scores, or return controller-owned `quality_scores`.
The report's **Resolved Quality Gates** are the thresholds from resolved project
configuration; the report values and verdicts are authoritative.

If the injected section or report is missing, return `BLOCKED` with the exact
missing path. A report with failed gates is valid evidence, not an operational
error: continue the qualitative review and explain concrete repairs.

## Dispatch Contract

<context>

- Authoritative active artifact root: `{spec_dir}` (`ACTIVE_SPEC_DIR` in the
  harness-injected Squad Run Context).
- `{spec_dir}/spec.md`
- `.specify/memory/constitution.md`
- `{spec_dir}/assumptions.md`
- prior/current/stale run context files at their harness-injected resolved paths
- reasoning journal summary from `phase1-what`
- harness-injected Certified Understanding Evidence at its exact report path
- `agents/exploration/templates/sage-quality-gates-template.md`
- `agents/exploration/templates/sage-issues-template.md`

</context>

<instructions>

Treat `{spec_dir}` / `ACTIVE_SPEC_DIR` as authoritative. Do not search for,
discover, or select another specification directory. Every context artifact is
identified by the resolved filesystem path in its injected heading.

Operate in WHY2 spec-validation mode using `agents/exploration/sage.md`. Audit
ambiguity, completeness, consistency, testability, assumptions, error cases,
and unknown unknowns. Interpret every failed certified gate and relevant
per-requirement finding. Copy certified values exactly into `quality-gates.md`;
do not create substitute values. Create both artifacts using the provided templates
as their schemas.

When Product Input Contract paths are present, audit every `IN-REQ-*` mapping
against `{spec_dir}/spec.md`. Return corrective `product_input_updates` for
unsupported included mappings, unresolved questions, or conflicts, preserving
canonical fields exactly. Do not edit the controller-owned ledger.

Return journal entries in `echelon_result.journal_entries` and a qualitative
`PASS`, `FAIL`, or `BLOCKED` verdict. Do not include `quality_scores` in state
updates or in `echelon_result.state_updates`.

</instructions>

<outputs>

Produce in `{spec_dir}/`:

- `{spec_dir}/issues.md` with CRITICAL, HIGH, MEDIUM, and LOW findings;
- `{spec_dir}/quality-gates.md` containing the certified metrics and SAGE
  interpretation;
- one final fenced `echelon_result` YAML block matching the harness-injected
  result contract.

</outputs>

## Gate and Convergence

The controller combines SAGE's qualitative result with its certified score:

1. Certified gates pass, no CRITICAL issues, and no required amendments remain:
   proceed to the assessment checkpoint.
2. Certified gates fail, a CRITICAL issue exists, or a required amendment
   remains: route to WHAT with the concrete amendment list while below the
   iteration limit.
3. At the iteration cap, use the workflow's explicit force-convergence warning.

SAGE may make a certified pass stricter through a qualitative FAIL. SAGE may
never make a certified failure pass. Score history, deltas, and iteration
routing are controller-owned. Required amendments are mandatory amendments:
even without a CRITICAL issue, HIGH issues marked required keep the verdict at
`FAIL` until repaired.

## User-Gated Critical Issues

Set `escalation_question`, `blocked_reason`, and `status: blocked` only when all
of these are true:

1. No squad agent can resolve the issue.
2. The answer requires information only the user holds.
3. Proceeding would require an arbitrary decision that binds downstream work.

Route squad-solvable issues back to WHAT without user escalation.

**Transition:** `phases[phase1-why2]` in `workflow/definition.yaml`.
