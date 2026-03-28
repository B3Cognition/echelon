# Feedback Directory

This directory closes the learning loop input side.

## Required Step

After every project that used the cognitive squad, run:

```bash
/speckit.cognitive-squad.feedback {spec_id}
```

This command collects post-implementation outcome data and writes a feedback file here.
Without feedback files, `calibration-profile.yaml` uses only proxy-estimated values and the
system cannot improve its accuracy over time.

## Schema

Each feedback file is named `feedback-{spec_id}-{timestamp}.yaml` and has this structure:

```yaml
# feedback-007-1774677025.yaml
spec_id: "007"
run_id: "squad-1774677025"
feature: "cognitive-squad-6-connections"
completed_at: "2026-03-28T00:00:00Z"
domain: "cognitive-orchestration"

estimates:
  predicted_hours: 3.5           # from estimates.md at analysis time
  actual_hours: null             # fill in after implementation
  adjustment_factor: null        # actual / predicted (computed automatically)

quality:
  overall_score: 0.6399          # from final WHY pass
  testability_score: 0.4873
  spec_quality_grade: "B"        # A=0.80+, B=0.70+, C=0.60+, D=below

outcomes:
  requirements_met: null         # true/false after implementation
  rework_cycles: null            # how many times did IMPLEMENTER loop?
  bugs_found_post_build: null    # bugs found after build completed
  spec_accuracy: null            # did spec.md correctly predict what was built?

notes: ""                        # free text observations
```

## Cold-Start Threshold

COMMANDER begins applying calibration corrections after **3 feedback files** exist for a domain.
Below this threshold, values are logged but not used as correction factors.
Stable calibration (±5% accuracy) typically requires **20+ feedback entries** per domain.

## Privacy

Feedback files contain only project metadata (hours, quality scores, outcome counts).
No source code, no business logic, no user data is stored here.
