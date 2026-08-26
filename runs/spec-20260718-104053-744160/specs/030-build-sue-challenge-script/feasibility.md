# Feasibility Assessment — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Gatekeeper: speckit-echelon-gatekeeper (GATEKEEPER)
- Mode: first-pass
- Date: 2026-07-18

## Feasibility Verdict

| Dimension | Verdict | Rationale | Evidence |
|-----------|---------|-----------|----------|
| Technical | FEASIBLE_WITH_RISKS | The deliverable is a standalone Python standard-library script (argparse, subprocess, tempfile, json) plus a pytest unit-test file — all known technology with a direct repository precedent (`scripts/contradiction-scanner.py` establishes the exact standalone shape, and `src/harness/llm_provider.py` proves subprocess-driven `claude -p` works). Two external-CLI assumptions remain unvalidated and gate the HOW phase, not buildability: A-001 (raw output shape drives the FR-026 extraction contract, OQ-001) and A-002 (temporary-working-directory isolation completeness, OQ-002). Both carry concrete pre-HOW spike plans; neither is a research unknown of the "may be impossible" kind. | spec.md FR-001 to FR-045; assumptions.md A-001, A-002, A-003; spec.md OQ-001, OQ-002; reasoning journal entries 3, 4, 22 |
| Resource | FEASIBLE | No team, budget, or timeline constraints are stated anywhere in the inputs, so this assessment uses a single-developer baseline (flagged as an assumption, not a fact). The scope is one script of roughly 500–800 lines plus one unit-test file; the calibrated effort range (see estimates.md) is 0.10–0.60 person-weeks LLM-assisted, well within a single developer's capacity with zero additional dependencies to procure (NFR-002 mandates stdlib-only operation). | spec.md NFR-002, In Scope (MVP) list; estimates.md effort range; assumptions.md A-012 |
| Domain | FEASIBLE | The specification describes a logically coherent system: a two-round dialogue with a deterministic assembly stage, a fully specified exit-code state machine, and assigned behavior for every degenerate outcome (empty question list, all-ANSWERED, over-cap truncation, unwritable directory). WHY2 passed all 8 quality gates with 0 CRITICAL and 0 HIGH issues; the 2 WARNING-level acceptance-criteria counting inconsistencies (issues.md ISS-201, ISS-203) are one-line rewordings, not domain contradictions that would make the system impossible. | issues.md Summary (verdict PASS, 0 CRITICAL, 0 HIGH); issues.md Contradiction Detection (2 WARNING, 0 BLOCKING); spec.md Edge Cases; quality gate scores in reasoning journal entry 40 |

## Key Risks

| Risk | Severity | Mitigation | Owner |
|------|----------|------------|-------|
| OQ-001 — `claude -p` raw output shape unknown; a wrong extraction contract converts systematic output noise into an exit-3 loop on every run (A-001) | HIGH | Run the OQ-001 spike before HOW freezes the FR-026 extraction design: one real call from a temporary working directory, capture raw stdout, CLI version, and flags; fold in the A-005 size measurement per issues.md ISS-209 | INVESTIGATOR (pre-HOW spike) |
| OQ-002 — operator-level ambient context may load independently of the working directory, silently biasing the reading (A-002) | MEDIUM | Run the OQ-002 marker-instruction spike before HOW freezes the subprocess runner; resolve traceably per TRACKER RF-3 — either documented suppression flags or a documented residual limitation, never a silent choice | INVESTIGATOR (pre-HOW spike) |
| Element-counting and render-time ambiguities (issues.md ISS-201, ISS-202, ISS-203) feed literal but wrong unit tests, e.g. an AC-011 stub test asserting the wrong prompt block count | MEDIUM | Apply the three one-line spec rewordings when spec.md is next touched, before SENTINEL enumerates tests; ISS-202 needs one assigned behavior for out-of-range evidence line references at render time | CARTOGRAPHER (WHAT amendment) |
| Acceptance-run flakiness against a nondeterministic model produces a false FAIL or goalpost moving | MEDIUM | Tolerance already encoded in AC-023 and SC-001 (overlap with at least 1 of 3 named issues, at most 3 attempts); re-verify or freeze the spec 029 acceptance anchors immediately before the run (A-004, validated at base commit ef2643c9) | SENTINEL / FINALIZE |
| Under pressure, implementation borrows the harness stream-json backend "because it already works", breaking the standalone contract (FR-045, A-003) and the stub test seam | LOW | Code-review gate: zero `harness.*` or `echelon.*` imports and zero orchestration configuration reads; boundaries.md records the harness as an explicit NON-boundary | CODE REVIEWER / SPEC GUARD |

## Kill / Defer / Pass Decision

- Decision: PASS
- Rationale: No feasibility dimension is UNFEASIBLE — Resource and Domain are FEASIBLE outright, and Technical is FEASIBLE_WITH_RISKS whose two risks (OQ-001, OQ-002) have concrete, cheap pre-HOW spike plans rather than open-ended research. The MVP scope is coherent: the must-ship set is the entire usable tool and matches the user's explicit "implement exactly the v1 scope" instruction (user-intent.md UI-004). Every feature scores far above any minimum RICE threshold against a 0.10–0.60 person-week effort range (see prioritization.md); the value-to-effort ratio makes a KILL or DEFER indefensible on the evidence.
- Scope notes: No scope reduction is recommended or permitted — TRACKER's intent model explicitly forbids MVP-style trimming of the six enumerated design areas (user-intent.md Scope Preferences, RF-2), and per Rule 3 this gate checked that intent before scoping. Won't-ship items are exactly the design's own out-of-scope list (later SUE tiers, workflow integration, report history, concurrency protection).
- Required follow-up: (1) INVESTIGATOR runs the OQ-001 and OQ-002 spikes before HOW freezes the extraction contract and subprocess runner; (2) CARTOGRAPHER applies the ISS-201/ISS-202/ISS-203 one-line rewordings at the next spec.md touch, before test enumeration; (3) re-verify or freeze the spec 029 acceptance target immediately before the live acceptance run (A-004).
