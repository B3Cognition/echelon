# Kill Report Template

```markdown
# Kill Report

**Date:** {ISO-8601}
**Feature:** {feature}
**Decision:** KILL

## Reason
{Concise explanation of the feasibility, value, risk, or constraint failure.}

## Evidence
| Evidence | Source | Confidence |
|----------|--------|------------|
| {fact} | {artifact/source} | {HIGH/MEDIUM/LOW} |

## Alternatives Considered
| Alternative | Why rejected |
|-------------|--------------|
| {option} | {reason} |

## User Options
1. Change constraints and rerun feasibility.
2. Reduce scope and rerun planning.
3. Archive the feature.

## Journal Summary
{Decision entry rationale for reasoning-journal.jsonl.}
```
