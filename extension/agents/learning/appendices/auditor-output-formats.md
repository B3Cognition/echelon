# Auditor Output Formats

## Calibration Profile Entry

```yaml
domains:
  {domain-name}:
    accuracy: {0.0-1.0}
    sample_size: {N}
    trend: "{stable|improving|declining}"
    correction_factor: {float}
    last_updated: "{YYYY-MM-DD}"
    notes: "{explanation of current state}"
```

## Auto Feedback Schema

Write to `knowledge-base/feedback/{spec-id}-{project-name}.yaml`:

```yaml
spec_id: "{spec-id}"
project_name: "{project-name}"
feedback_date: "{ISO-8601}"
feedback_source: "auto"
run_id: "{run_id}"

effort:
  estimated_total_hours: {N}
  actual_build_duration_minutes: {N}
  tasks_completed: {N}
  tasks_blocked: {N}
  tasks_degraded: {N}
  rework_cycles: {N}
  accuracy_ratio: {N}
  severity: "{severity}"

architecture_decisions:
  - decision: "{from plan.md}"
    held: "{yes|no|partially}"
    evidence: "{file path or reasoning-journal entry}"
    severity: "{severity}"

requirements:
  total_in_spec: {N}
  implemented_as_written: {N}
  needed_clarification: {N}
  missing_discovered_during_build: {N}
  unnecessary: {N}
  severity: "{severity}"

risks:
  predicted_count: {N}
  materialized_count: {N}
  unpredicted_blockers: {N}
  severity: "{severity}"

tests:
  planned_coverage: {0.0-1.0}
  actual_coverage: {0.0-1.0}
  severity: "{severity}"

critical_findings: []
```

## Feedback Report Sections

Write `specs/{feature}/feedback-report.md` with:

- Effort accuracy summary
- Architecture decision outcomes table
- Requirements coverage matrix
- Risk prediction accuracy
- Test strategy effectiveness
- Critical findings list for speckit-echelon-commander (COMMANDER) triage
