# Prioritization — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Gatekeeper: speckit-echelon-gatekeeper (GATEKEEPER)
- Mode: first-pass
- Date: 2026-07-18

## Scoring Conventions

RICE scales per GATEKEEPER protocol (no project override found in echelon config: `rice.*` keys unset): Reach 1–10, Impact 0.25/0.5/1/2/3, Confidence 0.5/0.8/1.0, Effort in person-weeks (LLM-assisted calibrated figures from estimates.md; the six features sum to the 0.28 person-week most-likely total including the acceptance run). RICE = (Reach × Impact × Confidence) / Effort. Kano classification is against the operator/author/maintainer stakeholders in 00-overview.md.

Features are the specification's five domain areas (00-overview.md Domain Areas) plus the mandated live acceptance run — the natural decomposition; per-FR scoring would be noise since all 45 FRs are marked MVP.

## Feature Ranking

| Feature | Kano | Reach | Impact | Confidence | Effort | RICE | Tier |
|---------|------|-------|--------|------------|--------|------|------|
| F1 Command interface & pre-flight validation (FR-001–FR-007, ERR-001/002) | Must-be | 10 | 3 | 1.0 | 0.03 | 1000 | must |
| F4 Deterministic assembly & report (FR-032–FR-042, NFR-004) | Must-be | 10 | 3 | 1.0 | 0.05 | 600 | must |
| F2 Model invocation & isolation (FR-008–FR-013, ERR-003/005) | Must-be | 10 | 3 | 0.8 | 0.05 | 480 | must |
| F6 Manual live acceptance run (SC-001, AC-023) | Must-be | 5 | 2 | 0.8 | 0.02 | 400 | must |
| F5 Test seam & unit tests (FR-043–FR-045, NFR-002) | Must-be | 8 | 2 | 1.0 | 0.05 | 320 | must |
| F3 Round schemas, extraction, validation & retry (FR-014–FR-031, ERR-004) | Must-be | 10 | 3 | 0.8 | 0.08 | 300 | must |

Confidence notes: F2 and F3 carry 0.8 (not 1.0) because their effort estimates depend on the unvalidated A-002 and A-001 assumptions respectively (OQ-002/OQ-001 spikes pending); F6 carries 0.8 for model nondeterminism, already tolerance-bounded by AC-023. Everything else is deterministic local computation with fully assigned behavior — confidence 1.0.

## Natural Break Point

- Break point: none within v1 — all six features are Must-be and every RICE score (300–1000) sits far above any plausible minimum threshold (`rice.minimum_threshold` unset; even a conservative threshold of 10 would pass all features by an order of magnitude). The only break is the design's own v1 boundary: everything after F6 is a later SUE tier.
- Reason: the features are serially load-bearing, not competing — F1→F2→F3→F4 is the single execution pipeline (00-overview.md Dependency Graph), F5 is an explicitly enumerated deliverable (user_message: "and pytest unit tests as designed"), and F6 is the only live validation. Dropping any one of them yields a non-working or non-verifiable tool.
- User-intent alignment: exact. user-intent.md UI-004 ("Implement exactly the v1 scope … 'exactly' cuts both ways") and the Scope Preferences table explicitly prohibit MVP-style prioritization trimming any of the six areas; this ranking therefore orders build risk/value, it does not tier scope.

## Low-Value Or Deferred Features

| Feature | Reason | User Intent Risk |
|---------|--------|------------------|
| (none within v1) | All v1 features are Must-be per the approved design and the user's "exactly the v1 scope" instruction | Trimming any v1 feature is the exact fidelity-erosion failure mode TRACKER flags (RF-1/RF-2) |
| Multi-reader consensus, interpretation graphs, convergence scoring | Later SUE tiers by design; the v1 interface is the stable seam they build on | None — deferral is the designed intent (UI-005, UI-012) |
| Workflow integration / echelon CLI verb; encode-back of answers; report history; concurrent-run protection; context-window guard | Explicitly out of scope in spec.md; adding any of them would be scope expansion the user prohibited | None if deferred; HIGH if smuggled in via unknown-resolution creep (RF-2) |
