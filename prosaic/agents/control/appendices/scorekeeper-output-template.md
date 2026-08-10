# Agent Scorecard — Run {RUN_ID}

## Leaderboard

| Rank | Agent | Score | Badges | Highlights |
|------|-------|-------|--------|------------|
| 1 | SCIENTIST | +18 | ★★★ Scientist of the Run | API constraint investigation changed transport architecture |
| 2 | WHY | +15 | ★★★ Bug Hunter | Caught 4 CRITICAL spec issues |
| 3 | echelon-implementer (IMPLEMENTER) | +12 | ★★ Perfect Sprint | 8/10 first-pass approvals |
| 4 | echelon-spec-guard (SPEC GUARD) | +10 | ★★★ Guardian Angel | Zero gaps in verification |
| 5 | HOW | +9 | ★★ | All 12 ADRs survived implementation |
| ... | | | | |

## Peer Appreciation

| From | To | Type | Reason |
|------|----|------|--------|
| echelon-implementer (IMPLEMENTER) | HOW | "Clear and actionable" (+2) | ADR code examples eliminated ambiguity |
| echelon-code-reviewer (CODE REVIEWER) | SCIENTIST | "Unblocked my work" (+3) | API constraint proof prevented wrong transport choice |
| echelon-spec-guard (SPEC GUARD) | WHY | "Caught my mistake" (+2) | WHY₂ caught testability gap I would have missed |

## Self-Healing Recommendations

| Agent | Signal | Recommendation |
|-------|--------|----------------|
| ASSESS | Optimist badge (estimates 1.4x off) | Increase correction factor to 1.5x |
| echelon-test-guardian (TEST echelon-guardian (GUARDIAN)) | Score +2 (low) | Add more specific test pattern examples to prompt |

## Run Summary

- **Total agents active:** {N}
- **Total points awarded:** +{N} / -{N}
- **Average score:** {N}
- **Badges earned:** {N}
- **Self-healing actions:** {N}

## Token Efficiency

| Agent | Tokens Used | Dispatches | Avg/Dispatch | Efficiency |
|-------|------------|------------|--------------|------------|
| echelon-implementer (IMPLEMENTER) | 45000 | 12 | 3750 | normal |
| echelon-spec-guard (SPEC GUARD) | 18000 | 6 | 3000 | efficient |
| ... | | | | |

**Squad total:** {total} / {budget} ({percentage}%)
**Most efficient:** {agent} ({rating})
**Least efficient:** {agent} ({rating})

## Marketplace Metrics

| Metric | Value |
|--------|-------|
| Total marketplace patterns | {count} |
| Patterns reused this run | {count} |
| Most reused pattern | {name} ({reuse_count} times) |
| Community Contributor badges awarded | {count} |

## Internalization Trend

| Agent | Composite | Absorption | Accuracy | Calibration | Transfer | Trend | Δ vs Prev |
|-------|-----------|------------|----------|-------------|----------|-------|-----------|
| echelon-architect (ARCHITECT) | 0.88 | 0.91 | 0.85 | 0.87 | 0.82 | improving | +0.04 |
| echelon-implementer (IMPLEMENTER) | 0.72 | 0.78 | 0.71 | null | null | declining | -0.06 |
| echelon-scout (SCOUT) | 0.80 | 0.82 | 0.79 | null | null | stable | +0.01 |
| SPEC_GUARD | null | null | null | null | null | insufficient_data | — |

### Internalization Alerts

| Agent | Alert | Details |
|-------|-------|---------|
| echelon-implementer (IMPLEMENTER) | declining trend | Composite dropped 0.06 over last 3 runs — Accuracy category weakest |
| {agent} | cold-start | Phase 1 — Calibration and Transfer metrics unavailable |
