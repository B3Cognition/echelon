# Endocrine System Calibration Guide

This guide explains how to enable, calibrate, and tune the endocrine (hormone-modulated motivation) system for the Echelon.

## What is the Endocrine System?

The endocrine system provides bio-inspired urgency signals that modulate agent behavior based on budget pressure, task complexity, and run phase. When enabled, it injects prompt modifiers that steer agents between thorough exploration (low adrenaline) and focused efficiency (high adrenaline).

Phase 1 uses adrenaline only. Phases 2-4 add dopamine, cortisol, serotonin, oxytocin, and norepinephrine.

## How to Enable

In `echelon-config.yml`, set:

```yaml
endocrine:
  enabled: true
  phase: 1  # start with phase 1
```

When `enabled: false` (the default), all endocrine processing is skipped. No prompt modifiers are injected.

## How Calibration Works

The endocrine system uses baseline hormone values per agent archetype (exploration, validation, build, learning, etc.). These baselines determine each agent's default urgency level. Out-of-the-box baselines are reasonable defaults, but they may not be optimal for your specific domain or team workflow.

Calibration collects data across multiple runs and identifies which hormone levels correlate with successful gate outcomes (PASS) versus failures (FAIL) for each agent.

## Running Calibration

### Step 1: Collect Data (10+ runs)

Run at least 10 full squad sessions with `endocrine.enabled: true`. Each run records hormone events in `state.json` under `hormone_history`. The state-backup system preserves these across phase transitions.

```bash
# Normal squad runs — just ensure endocrine is enabled
# The system automatically records hormone events
```

### Step 2: Run the Calibration Script

After 10+ runs:

```bash
# From repo root
scripts/bash/calibrate-endocrine.sh

# With custom state directory
scripts/bash/calibrate-endocrine.sh --state-dir squad/<run-id>

# Save report to file
scripts/bash/calibrate-endocrine.sh --output calibration-report.md

# Verbose mode (progress to stderr)
scripts/bash/calibrate-endocrine.sh --verbose --output calibration-report.md
```

The script will output "Insufficient Data" if fewer than 10 runs are available.

### Step 3: Interpret Results

The report contains:

#### Per-Agent Hormone Correlation Table

```
| Agent | Avg Adrenaline at Success | Avg Adrenaline at Failure | Suggested Baseline | Delta |
```

- **Avg Adrenaline at Success**: Mean adrenaline level when this agent's gates passed
- **Avg Adrenaline at Failure**: Mean adrenaline level when gates failed
- **Suggested Baseline**: Recommended new baseline (weighted 70% toward success average)
- **Delta**: Absolute difference between success and failure averages

**Interpreting Delta:**
- Delta > 1.0: Strong signal. Adjusting baseline is likely to help.
- Delta 0.3-1.0: Moderate signal. Adjustment may help.
- Delta < 0.3: Weak signal. Hormone level has little correlation with outcomes for this agent.

**Interpreting Direction:**
- Success adrenaline > Failure adrenaline: Agent performs better under pressure. Consider raising baseline.
- Success adrenaline < Failure adrenaline: Agent performs worse under pressure. Consider lowering baseline.

#### Gate Outcome Distribution

Overall pass/fail counts and rates. If overall pass rate is below 70%, consider whether the issue is baselines or something else (spec quality, agent prompts, etc.).

#### Recommended Baseline Adjustments

Copy-pasteable YAML snippet for `echelon-config.yml`. Review before applying — these are suggestions, not commands.

### Step 4: Update Baselines

Edit `echelon-config.yml` and update the archetype baselines:

```yaml
endocrine:
  baselines:
    exploration: [4.0, 5.0, 4.0, 5.0, 5.0, 3.0]  # [adr, dop, cor, ser, oxy, nor]
    validation:  [6.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    build:       [5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    learning:    [3.0, 5.0, 4.0, 5.0, 5.0, 4.0]
    # ... adjust based on calibration report
```

The first value in each array is adrenaline (the only active hormone in Phase 1).

### Step 5: Validate

Run 3-5 more sessions with the new baselines and compare gate pass rates. If pass rate improves, the calibration was effective.

## Calibration Cadence

- **Initial**: After first 10 runs
- **Ongoing**: Every 20 runs, or when gate pass rates drop below 75%
- **After prompt changes**: Re-calibrate after significant agent prompt modifications (prompt version changes in prompt-versions.yaml)

## Troubleshooting

**Q: The script says "No state files found"**
A: Ensure `endocrine.enabled: true` is set and you have run at least one session. Check that the active run's `state.json` exists (`runs/.current` or `squad/.current` points to the run directory).

**Q: All values show N/A**
A: The hormone_history may not be recording events. Verify that `endocrine.sh log_hormone_event` is being called during runs (check COMMANDER dispatch logs).

**Q: Baselines did not improve pass rates**
A: The endocrine system is one factor among many. If spec quality is low or agent prompts need tuning, baselines alone will not fix outcomes. Check the calibration dashboard and internalization metrics for root causes.

**Q: Can I disable endocrine for specific agents?**
A: Not directly. All agents receive hormone modifiers when endocrine is enabled. However, the `control` archetype uses moderate baselines that produce minimal behavioral modification.
