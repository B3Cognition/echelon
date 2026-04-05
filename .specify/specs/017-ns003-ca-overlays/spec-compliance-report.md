# Spec Compliance Report — Spec 017 NS-003 + U-CA-004

**Build run**: squad-1775169176 (continued)
**Date**: 2026-04-03
**Constitution version**: 1.1.0


## Batch SPEC GUARD — T-001 through T-019

**Reviewed**: 2026-04-03 | **Reviewer**: CODE REVIEWER subagent (squad-1775169176)

| Task | Verdict | Finding |
|------|---------|---------|
| T-001 | WARN | `jsonschema` declared but not imported (will be fixed); `pyyaml` unused |
| T-002 | PASS | No credentials; --help smoke tests present |
| T-003 | PASS | Amendment record complete; amended framing canonical |
| T-004 | PASS | All three functions correct; stdlib only |
| T-005 | WARN | `required_sections` non-standard; enum/type constraints defined but enforcement gap |
| T-006 | FAIL | FR-NS3A-001: `jsonschema.validate()` never called — ROUTED TO IMPLEMENTER FOR FIX |
| T-007 | PASS | Prose confidence [0.5,0.85]; TIMEOUT handled; HTTP 401 partial-results correct |
| T-008 | PASS | FPCR dual threshold; exit codes correct |
| T-009 | PASS | BeliefNode, ConflictSignal correct; error classes correct |
| T-010 | PASS | K*2 postulates; atomic write via tempfile+rename |
| T-011 | PASS | Pipeline DISCOVER→LEARN order; unrecognized files warned |
| T-012 | WARN | scope_conflict over-fires on any incoming scope term — ROUTED TO IMPLEMENTER |
| T-013 | PASS | pre-commit notice present; exit codes correct |
| T-014 | PASS | Git hash; FRR gate; IS-010 deviation section |
| T-015 | PASS | ADR-001 framing; FPCR dual threshold; coverage limitation |
| T-016 | PASS | Fixed prompt v1.0.0; SHA-256 hash; JSONL audit; retry logic |
| T-017 | PASS | N=20 per condition; TIMEOUT counts against N |
| T-018 | PASS | VOID before stats; p<0.05 AND d≥0.5 binary gate |
| T-019 | PASS | Only on NEGATIVE; disclosures verbatim |

**Gates triggered**: T-006 FAIL → IMPLEMENTER rework cycle 1. T-012 WARN → IMPLEMENTER fix.
