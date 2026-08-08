# Phase: phase1-why2
# Agent: echelon.sage (SAGE), mode WHY2

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
- `.echelon/constitution.md`
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

Return journal entries in `echelon_result.journal_entries` and exactly one
qualitative `PASS`, `FAIL`, or `STOP_AND_ASK` verdict. `DONE` is not a valid
WHY2 verdict because it does not certify whether the specification may advance.
Do not include `quality_scores` in state updates or in
`echelon_result.state_updates`.

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
   return `PASS`; the controller certifies the exact spec content and proceeds
   to derived Lexicon authoring (or directly to assessment when that gate is
   disabled).
2. Certified gates fail, a CRITICAL issue exists, or a required amendment
   remains: route to WHAT with the concrete amendment list while below the
   iteration limit.
3. At the iteration cap, the controller blocks. Do not claim best-effort
   convergence or waive failed quality.

SAGE may make a certified pass stricter through a qualitative FAIL. SAGE may
never make a certified failure pass. Score history, deltas, and iteration
routing are controller-owned. Required amendments are mandatory amendments:
even without a CRITICAL issue, HIGH issues marked required keep the verdict at
`FAIL` until repaired.

## Evidence Resolution Routing

Classify each failed finding before choosing a repair route:

- `spec_repair`: CARTOGRAPHER can repair it from evidence already present in
  the active artifact root; return an ordinary `FAIL` and do not request
  investigation.
- `evidence_resolution`: a project-specific fact must be established from a
  declared reference input, its directly relevant primary material, a
  repository, a database export or snapshot, or a permitted read-only service.
  Return `FAIL` with the exact state updates below.
- `human_decision`: the answer requires the user's policy, scope, or authority;
  use the User-Gated Critical Issues protocol below.

For `evidence_resolution`, return a machine-readable request. Do not merely
write “route to INVESTIGATOR” in prose:

```yaml
echelon_result:
  verdict: FAIL
  state_updates:
    evidence_resolution_status: pending
    evidence_requests:
      requests:
        - id: ER-001
          question: "<project-specific fact to establish>"
          affected_requirements: [FR-001]
          evidence_needed: "<minimum authoritative evidence required>"
          supplied_reference_ids: [IN-REF-...]
```

Every WHY2 result MUST also classify its findings in the control plane. For a
passing review return `evidence_resolution_status: not_required` with an empty
list. For a failing review, include one entry for every blocking finding. The
`route` value must be exactly `spec_repair`, `evidence_resolution`, or
`human_decision`:

```yaml
echelon_result:
  state_updates:
    evidence_resolution_status: not_required # or pending
    finding_routes:
      findings:
        - issue_id: ISS-001
          route: evidence_resolution
          rationale: "A declared primary reference must establish the fact."
```

For every finding, write `Action Required` and a `### Resolution Guidance`
subsection inside that issue's `issues.md` block. It must state the exact next
action or project decision, one evidence-backed suggested option if one exists,
and which values cannot be inferred. Never suggest a retry as the resolution.
Mark `Banzai eligible: yes` only for a fully evidence-backed option that does
not decide product policy, scope, requirements, security posture, or a quality
waiver. Banzai COMMANDER may select only that exact option; all other choices
remain human decisions.

If any finding has `route: evidence_resolution`,
`evidence_resolution_status` MUST be `pending` and a complete
`evidence_requests` object is required. If none do, status MUST be
`not_required` and omit `evidence_requests`. NEVER use an agent-authored
`BLOCKED` verdict for a routeable evidence gap; it is rejected before routing.

Create a request only when the missing fact cannot be resolved by amending the
specification. Every request must name the affected requirement and the
minimum evidence needed. Never request an investigation based only on a generic
best practice or an unsupported inference.

## User-Gated Critical Issues

Return a question only when all of these are true:

1. No squad agent can resolve the issue.
2. The answer requires information only the user holds.
3. Proceeding would require an arbitrary decision that binds downstream work.

Route squad-solvable issues back to WHAT without user escalation.

Every question-bearing result uses this exact controller input:

```yaml
echelon_result:
  verdict: STOP_AND_ASK
  state_updates:
    status: blocked
    blocked_reason: human_clarification_required
    escalation_question: "<one concrete project decision>"
    escalation_recommended_answer: "<evidence-backed recommendation>"
    escalation_risk_level: "<low | medium | high | critical>"
```

Include `escalation_recommended_answer` and `escalation_risk_level` together
only when evidence supports a recommendation; otherwise omit both. Never put a
question on `FAIL`, `BLOCKED`, or `ESCALATE`. The controller owns
clarification writes and state cleanup.

**Transition:** `phases[phase1-why2]` in `workflow/definition.yaml`.
