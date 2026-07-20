# Auditor Output Formats

Do not edit canonical knowledge-base files directly. Treat the schemas below as
run-local review artifacts or proposal payload examples for deterministic KB
application.

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

Use this shape for run-local feedback review artifacts and future feedback
proposal payloads:

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

Write `{spec_dir}/feedback-report.md` using the complete
`extension/templates/feedback-report-template.md`. This appendix retains only
the auto-feedback YAML schema above; the template is the canonical Markdown
format for the report.
