---
description: "Periodic health check — validates specs still match code, estimates still realistic"
behavior:
  invocation: automatic
---

## User Input

$ARGUMENTS

## Purpose

Run periodic health checks on existing squad artifacts. Catches spec drift, stale estimates, and evolving risks.

## Checks

1. **Spec-Code Drift:** Run VERIFICATION in check-only mode — is the traceability matrix still accurate?
2. **Estimate Drift:** Compare PROGRESS TRACKER's latest CPI/SPI against initial ASSESS estimates
3. **Risk Drift:** Re-run STRATEGIC OVERVIEW — has the risk profile changed since last check?
4. **Constitution Compliance:** Scan recent code changes against constitution rules
5. **Knowledge Base Freshness:** Check for stale patterns/pitfalls (>6 months, no feedback)

## Scheduling

This command can be triggered manually or scheduled:
- Weekly: basic drift check (spec-code + constitution)
- Monthly: full health check (all 5 checks)
- On PR merge: constitution compliance scan

## Output

health-report.md:
- Drift detected: {yes/no per category}
- Recommendations: {what to re-validate}
- Action needed: {human review required / auto-correctable}
