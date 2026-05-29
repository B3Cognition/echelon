# Auditor Dashboard Templates

## Domain Calibration Overview

```markdown
## Domain Calibration Overview

| Domain | Accuracy | Trend | Correction Factor | Sample Size | Risk Level |
|--------|----------|-------|-------------------|-------------|------------|
| backend | 0.82 | improving | 1.05 | 12 | LOW |
| frontend | 0.61 | declining | 0.85 | 8 | MEDIUM |
| security | 0.45 | stable | 1.30 | 4 | HIGH |
```

Risk levels: HIGH (accuracy < 0.5), MEDIUM (0.5-0.75), LOW (> 0.75).

## Evolution Signals

```markdown
## Evolution Signals

| Signal ID | Trigger | Severity | Status | Affected Domain |
|-----------|---------|----------|--------|-----------------|
| evo-sig-012 | declining_trend | HIGH | open | frontend |
```

## Calibration Analytics

```markdown
# Calibration Analytics

## Accuracy Trend
| Run | Date | Domain | Predicted | Actual | Accuracy | Correction |
|-----|------|--------|-----------|--------|----------|-----------|
| 001 | ... | ... | ... | ... | ... | ... |

## Domain Performance
| Domain | Avg Accuracy | Trend | Sample Size | Confidence |
|--------|-------------|-------|-------------|-----------|
| ... | ... | improving/stable/declining | ... | high/medium/low |

## Agent Performance Over Time
| Agent | Run 1 | Run 2 | Run 3 | Trend |
|-------|-------|-------|-------|-------|
| ... | ... | ... | ... | improving/stable/declining |

## Key Insights
- {what's getting better}
- {what's getting worse}
- {recommended adjustments}
```
