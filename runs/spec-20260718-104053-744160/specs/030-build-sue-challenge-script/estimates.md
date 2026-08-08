# Estimates — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Gatekeeper: speckit-echelon-gatekeeper (GATEKEEPER)
- Mode: first-pass
- Date: 2026-07-18

## Function Point Breakdown

Counted from spec.md functional requirements and Key Entities using standard IFPUG weights (EI 3/4/6, EO 4/5/7, EQ 3/4/6, ILF 7/10/15, EIF 5/7/10 for Low/Average/High).

| Type | Count | Complexity | Weight | UFP |
|------|-------|------------|--------|-----|
| External Inputs | 1 (challenge-run invocation: 1 positional + 3 options + pre-flight, FR-001–FR-007) | Average | 4 | 4 |
| External Inputs | 1 (round-1 output ingestion: extraction + schema validation + truncation, FR-016–FR-019, FR-026) | Average | 4 | 4 |
| External Inputs | 1 (round-2 output ingestion: extraction + schema validation + identifier bijection, FR-024–FR-027) | High | 6 | 6 |
| External Outputs | 1 (challenge report: 3 sections, ranking, per-line evidence quoting, collapsed audit appendix, FR-032–FR-039, FR-041) | High | 7 | 7 |
| External Outputs | 2 (round-1 prompt FR-014; round-2 prompt with exclusion rules FR-021–FR-023) | Average | 5 | 10 |
| External Outputs | 3 (terminal summary FR-040; debug dump FR-030; diagnostic error lines NFR-005) | Low | 4 | 12 |
| External Inquiries | 1 (usage/help text including the NFR-003 egress disclosure) | Low | 3 | 3 |
| Internal Logical Files | 0 (no data maintained across runs — the report is regenerable output, reruns overwrite, no history by design) | — | — | 0 |
| External Interface Files | 1 (challenged specification file: read-only evidence source, FR-042, FR-045) | Low | 5 | 5 |

**Unadjusted Function Points: 51**

## Calibration Adjustment

| Source | Correction Factor | Applied | Notes |
|--------|-------------------|---------|-------|
| calibration-profile.yaml | none exact; 0.08–0.16 observed in adjacent domains | partially | No domain matches "standalone Python tool with unit tests". Feedback-backed adjacent datapoints: cognitive-orchestration 0.08 (md/yaml edits — 12.5× overestimate vs human reference class) and prompt-engineering 0.16 (batch prompt edits). Real Python code with a live-CLI spike and pytest suite is less compressible than config edits, so a conservative 0.2–0.3 factor is applied to the human-reference figure rather than 0.08, and the confidence interval is widened per the uncalibrated-domain rule. Proposing new domain key `standalone-python-tool` for the knowledge base after feedback. |
| estimates-log.yaml reference class | no usable reference class | no | No prior entry is a Python-code implementation with recorded actual_hours; est-003/est-006/est-007 (the only feedback-backed entries) are md/yaml or prompt edits. Reference class forecasting degrades to the cross-domain observation above. First run in this domain: estimates are uncalibrated — interval widened accordingly. |

## Effort Range

Human-developer reference class first (what FPA natively yields at ~1.5 h/FP for a small scripting-language tool: 51 UFP ≈ 76 h ≈ 1.9 person-weeks most likely), then the estimate of record after LLM-assisted correction. Cone of Uncertainty at post-specification stage is nominally ×0.67–×1.5; widened to roughly ×0.4–×2.4 here because the domain is uncalibrated.

| Estimate | Person-Weeks | Confidence |
|----------|--------------|------------|
| Optimistic | 0.10 (~4 h; includes both pre-HOW spikes going cleanly) | low |
| Most likely | 0.25 (~10 h; script + full unit-test suite + spikes + report polish) | low |
| Pessimistic | 0.60 (~24 h; extraction contract needs redesign after the OQ-001 spike, acceptance run consumes all 3 attempts) | low |

Human-developer reference range for comparison: 0.8 / 1.5 / 2.5 person-weeks (optimistic / most likely / pessimistic). Including the acceptance-run overhead, prioritization.md allocates a 0.28 person-week most-likely total across the six features.

## Assumptions

| Assumption | Impact If Wrong |
|------------|-----------------|
| Single-developer baseline (no team/budget/timeline constraints stated anywhere in the inputs — flagged as an issue per protocol, estimated on the single-developer default) | Effort range unchanged in person-weeks; calendar time scales with actual staffing |
| LLM-assisted execution at 0.2–0.3 of human reference class (extrapolated from adjacent domains, not measured for Python code) | If closer to 1.0, the human-reference range (0.8–2.5 person-weeks) governs; still FEASIBLE, no gate impact |
| A-001 holds: `claude -p` output is extractable per the FR-026 contract (OQ-001 spike pending) | Extraction redesign inside the pessimistic bound; if fundamentally unextractable, feasibility re-opens — treat as a DEFER trigger at HOW, not a build surprise |
| A-004 holds: spec 029 acceptance anchors still present at run time (validated at base commit ef2643c9) | Acceptance target must be re-frozen; adds hours, not weeks |
| Effort excludes squad orchestration overhead (phase dispatches, WHY gates) — it counts implementation work only | Total run cost is tracked in state.json token/cost fields, not in this estimate |
