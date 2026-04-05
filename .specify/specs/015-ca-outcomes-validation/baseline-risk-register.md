# Baseline Measurement Risk Register — Spec 015
**Task**: TASK-011 | **Date**: 2026-04-02
**REQ**: REQ-015-003, REQ-015-004, REQ-015-005

## Risks

| Risk ID | Risk | Severity | Affected REQ | Mitigation | Residual Risk |
|---------|------|----------|--------------|------------|---------------|
| BR-001 | Prior run reasoning-journal.json files lack token count fields | HIGH | REQ-015-003 | Forward-looking instrumentation via token-logger.py; break-even in TASK-008 uses symbolic form | MEDIUM — baseline covers future runs only; historical estimation is approximate |
| BR-002 | Single annotator for scope violation baseline (TASK-005) | MEDIUM | REQ-015-004 | Explicit limitation statement per AC-004-003; results labeled as single-annotator | LOW — limitation stated; results still useful for order-of-magnitude baseline |
| BR-003 | Heuristic contradiction detection has high false positive rate | MEDIUM | REQ-015-005 | Output labeled upper_bound; 5-sample manual precision review included per AC-005-004 | MEDIUM — scanner results directional only; manual review required for precise rate |
| BR-004 | Fewer than 9 adjacent DISCOVER→ASSESS pairs available for NOVEL-004 calibration | MEDIUM | REQ-015-007 | Explicit N disclosure and small-sample limitation per AC-007-001; calibration still provides directional signal | LOW — small sample acknowledged; go/no-go treated as preliminary |

## Notes

All four mitigations are encoded in the relevant ACs (AC-003-005, AC-004-003, AC-005-004/005, AC-007-001). No mitigation requires additional engineering work beyond explicit disclosure.
