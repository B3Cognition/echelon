# Estimates Template

Use this template for `estimates.md`. It is a decision-support estimate, not a
commitment. Populate every required table with a range; do not leave a scenario,
token budget, or USD budget out because calibration, pricing, or scope data is
incomplete. State the assumption and widen the range instead.

## Metadata

| Field | Value |
|-------|-------|
| Spec | `{NNN-slug}` |
| Gatekeeper | `echelon-gatekeeper (GATEKEEPER)` |
| Mode | `first-pass` / `consensus` |
| Date | `{ISO-8601 date}` |
| Estimate revision | `{first-pass / ASSESS2 revision n}` |
| Scope basis | `{requirements, MVP tier, task count, or other evidence}` |
| Calibration status | `{calibrated / cold start}` |

## Estimation Conventions

- **Phase A — specification authoring** covers the work to produce and validate
  the Echelon specification set: discovery, requirements, feasibility,
  architecture, planning, test design, review, and correction loops.
- **Phase B — implementation** covers building, testing, integrating,
  documenting, reviewing, and releasing the agreed scope. Include external
  coordination and wait time separately; agentic coding does not eliminate it.
- Provide a **human-only** scenario and an **AI-assisted** scenario for both
  phases. AI-assisted effort includes the human direction, review, acceptance,
  and remediation that remain necessary; never apply a flat percentage reduction
  without identifying the work AI does and does not accelerate.
- All effort figures are three-point ranges. A person-week is `{hours per
  person-week, normally 40}` hours. Calendar duration must name the assumed team
  and parallelism, and must not be calculated by dividing effort when a critical
  dependency dominates.
- AI-assisted token and USD budgets are mandatory for every Phase A and Phase B
  estimate. Use a stated provider/model price or an approved effective internal
  rate. If pricing is unavailable, use a conservative provisional rate, label it
  `PROVISIONAL`, and add an assumption/risk; never silently omit the USD budget.

## Function Point Breakdown

Use Function Point Analysis for implementation scope where it is applicable.
If it is not applicable, retain the table, state why, and name the alternate
evidence used to estimate Phase B.

| Type | Count | Complexity | Weight | UFP |
|------|-------|------------|--------|-----|
| External Inputs | | Low/Average/High | | |
| External Outputs | | Low/Average/High | | |
| External Inquiries | | Low/Average/High | | |
| Internal Logical Files | | Low/Average/High | | |
| External Interface Files | | Low/Average/High | | |
| **Total** | | | | **0** |

### Calculation Notes

| Evidence / requirement group | FP or alternate sizing basis | Estimate impact |
|------------------------------|------------------------------|-----------------|
| | | |

## Calibration Adjustment

| Source | Correction Factor | Applied | Notes |
|--------|-------------------|---------|-------|
| `calibration-profile.yaml` | | yes/no | |
| `estimates-log.yaml` reference class | | yes/no | |
| Architecture / task evidence (ASSESS2 only) | | yes/no | |

**Cold-start treatment:** `{state absent calibration/reference data, the wider
interval used, and the evidence needed to calibrate the next estimate}`.

## Delivery Estimate Summary

This is the required executive view. The four rows are mandatory even when one
phase is out of scope; mark it `N/A — reason` only when it will genuinely not be
performed.

| Phase | Delivery approach | Optimistic effort | Most-likely effort | Pessimistic effort | Assumed team / human oversight | Calendar range | Confidence |
|-------|-------------------|------------------:|-------------------:|-------------------:|--------------------------------|----------------|------------|
| Phase A — specification authoring | Human-only | | | | | | |
| Phase A — specification authoring | AI-assisted (Echelon) | | | | | | |
| Phase B — implementation | Human-only | | | | | | |
| Phase B — implementation | AI-assisted (agentic coding) | | | | | | |
| **Total delivery** | **Human-only** | | | | | | |
| **Total delivery** | **AI-assisted** | | | | | | |

## Phase A — Specification Estimate

Estimate the specification work Echelon performs, not only the feature build.
Include rework expected at the current uncertainty level.

| Workstream | Human-only effort range | AI-assisted effort range | AI-assisted human oversight | Evidence / assumptions |
|------------|-------------------------|--------------------------|-----------------------------|------------------------|
| Discovery and context acquisition | | | | |
| Requirements, quality validation, and feasibility | | | | |
| Architecture, planning, and test design | | | | |
| Review, stakeholder decisions, and correction loops | | | | |
| **Phase A total** | | | | |

## Phase B — Implementation Estimate

Use the function-point or alternate size above, then account for the work that
does not scale with code generation.

| Workstream | Human-only effort range | AI-assisted effort range | AI acceleration / human-bound work | Dependencies and risks |
|------------|-------------------------|--------------------------|------------------------------------|------------------------|
| Implementation and migrations | | | | |
| Tests, verification, and rework | | | | |
| Integration, security, performance, and operations | | | | |
| Documentation, review, and release | | | | |
| External coordination / blocked time | | | | |
| **Phase B total** | | | | |

## AI-Assisted Token and USD Budget

These are planning budgets for the AI-assisted rows above, including expected
retries and review/fix loops. The `Total Tokens` and `USD Budget` columns must
be populated for Phase A, Phase B, and Total.

### Pricing Assumptions

| Field | Value |
|-------|-------|
| Provider / model(s) | |
| Price source and date checked | `{official pricing URL, internal rate card, or PROVISIONAL basis}` |
| Input price (USD / 1M tokens) | |
| Cached-input price (USD / 1M tokens), if used | `N/A` / |
| Output price (USD / 1M tokens) | |
| Budget contingency | `{percentage and rationale}` |
| Billing treatment | `{usage-based / subscription effective cost allocation}` |

| Workstream | Input Tokens | Output Tokens | Total Tokens | USD Budget | Pricing Basis |
|------------|-------------:|--------------:|-------------:|-----------:|---------------|
| Phase A — specification authoring | | | | | |
| Phase B — implementation | | | | | |
| Contingency / retries | | | | | |
| **Total AI-assisted delivery budget** | **0** | **0** | **0** | **$0.00** | |

**Calculation:** `{show the arithmetic using the stated input/output/cached
rates and contingency. Distinguish an API charge from a subscription-effective
cost when relevant.}`

## Effort Range

Explain the range drivers and reconcile this section with the executive summary.

| Scenario | Human-only effort | AI-assisted effort | Main range drivers | Confidence |
|----------|-------------------|--------------------|--------------------|------------|
| Optimistic | | | | |
| Most likely | | | | |
| Pessimistic | | | | |

## Assumptions and Sensitivity

| Assumption | Impact If Wrong | Trigger / validation point | Estimate response |
|------------|-----------------|----------------------------|-------------------|
| | | | |

## Recommendation

State the recommended planning scenario, including:

- Phase A and Phase B effort and calendar ranges;
- the recommended human-only and AI-assisted comparison;
- the AI-assisted total token and USD budget (with pricing basis); and
- the decision, dependency, or calibration event most likely to change the
  estimate.
