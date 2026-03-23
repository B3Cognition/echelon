# Calibration Dashboard — Run squad-010-1742652000

Generated: 2026-03-23T14:30:00Z

## Domain Calibration Overview

| Domain | Accuracy | Trend | Correction Factor | Sample Size | Risk Level |
|--------|----------|-------|-------------------|-------------|------------|
| backend | 0.82 | improving | 1.05 | 12 | LOW |
| frontend | 0.61 | declining | 0.85 | 8 | MEDIUM |
| security | 0.45 | stable | 1.30 | 4 | HIGH |
| database | 0.78 | stable | 1.00 | 10 | LOW |
| infrastructure | 0.52 | improving | 1.10 | 6 | MEDIUM |

## Agent Internalization Health

| Agent | Composite | Absorption | Accuracy | Calibration | Transfer | Trend | Phase |
|-------|-----------|------------|----------|-------------|----------|-------|-------|
| ARCHITECT | 0.88 | 0.91 | 0.85 | 0.87 | 0.82 | improving | 3 |
| IMPLEMENTER | 0.62 | 0.70 | 0.58 | null | null | declining | 1 |
| SCOUT | 0.80 | 0.82 | 0.79 | null | null | stable | 2 |
| SPEC_GUARD | null | null | null | null | null | insufficient_data | 1 |

## Cross-Validation Flags

| Agent | Flag | Rule | Triggering Metrics |
|-------|------|------|--------------------|
| IMPLEMENTER | high-terminology-low-accuracy | CV-2 | I-03=0.92, I-05=0.68 |

## Evolution Signals

| Signal ID | Trigger | Severity | Status | Affected Agents |
|-----------|---------|----------|--------|-----------------|
| evo-sig-012 | int_declining_trend | HIGH | open | IMPLEMENTER |
| evo-sig-013 | int_accuracy_drop | MEDIUM | acknowledged | SCOUT |

## Calibration Health Score

```
calibration_health = (3/5) * 0.4 + (2/4) * 0.4 + (1 - 1/2) * 0.2
                   = 0.24 + 0.20 + 0.10
                   = 0.54
```

**Calibration Health: 0.54 (DEGRADED)**

### Summary
- Domains above threshold: 3 / 5
- Agents passing int-gate: 2 / 4
- Open evolution signals: 1 / 2
- Domains at risk: security (HIGH)
- Agents declining: IMPLEMENTER
