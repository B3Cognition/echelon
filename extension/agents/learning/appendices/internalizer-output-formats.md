# Internalizer Output Formats

Do not edit canonical knowledge-base files directly. Treat the structures below
as review/proposal payload examples for deterministic KB application.

## Agent Scores Proposal Payload Format

Use this shape when proposing an agent-score refresh under each agent's entry:

```yaml
agents:
  {AGENT_NAME}:
    internalization:
      composite_score: 0.82
      category_scores:
        absorption: 0.88
        accuracy: 0.85
        calibration: 0.72
        transfer: 0.78
      metric_values:
        I_01_requirement_coverage_rate: 0.91
        I_02_constraint_adherence_score: 0.85
        I_03_terminology_fidelity: 0.88
        I_04_dependency_awareness: 0.87
        I_05_numeric_contradiction_rate: 0.90
        I_06_uncited_decision_rate: 0.82
        I_07_cross_reference_accuracy: 0.85
        I_08_keyword_scope_rate: 0.83
        I_09_confidence_accuracy: null
        I_10_doubt_signal_quality: null
        I_11_blind_spot_rate: null
        I_12_escalation_precision: null
        I_13_first_pass_acceptance: null
        I_14_rework_severity: null
        I_15_explicit_decision_traceability: null
        I_16_priority_alignment: null
      trend: "improving"
      run_id: "squad-005-1742652000"
      cold_start_phase: 1
      history:
        - run_id: "squad-004"
          composite_score: 0.79
          timestamp: "2026-03-22T10:00:00Z"
        - run_id: "squad-003"
          composite_score: 0.75
          timestamp: "2026-03-21T10:00:00Z"
```

## Internalization Log Proposal Fields

Each proposed internalization observation includes:

- `id`: next sequential `int-NNN`
- `run_id`: current run ID
- `source`: "echelon-internalizer (INTERNALIZER)"
- `agent`: agent codename
- `prompt_version`: the active version from prompt-versions.yaml
- `score`: the numeric score (0-6) from echelon-checkpoint (CHECKPOINT)'s report (informational only)
- `result`: PASS/PARTIAL/FAIL based on config thresholds
- `doubts_count`, `doubts_resolved`, `doubts_escalated`: from echelon-checkpoint (CHECKPOINT)'s report
- `doubt_categories`: map each doubt to one of: `role`, `constraints`, `architecture`, `domain`, `tasks`, `doubts`
- `resolution_types`: map each resolution to one of: `artifact_read`, `clarification`, `escalation`, `deferred`
- `downstream_outcome`: set in Step 8
- `downstream_agent`: set in Step 8
- `int_absorption_score`, `int_accuracy_score`: category scores
- `int_gate_verdict`: PASS/FAIL/EXEMPT/INSUFFICIENT_DATA
- `cross_validation_flags`: array (from Step 4)
- `disagreement_flag`: string or null (from Step 5)
- `computation_health`: per-metric health records
- `metric_values`: all 16 I-* values (null where not computed)

## Agent Internalization Health Dashboard Section

```markdown
## Agent Internalization Health

| Agent | Composite | Absorption | Accuracy | Calibration | Transfer | Trend | Phase |
|-------|-----------|------------|----------|-------------|----------|-------|-------|
| echelon-architect (ARCHITECT) | 0.88 | 0.91 | 0.85 | 0.87 | 0.82 | improving | 3 |
| echelon-implementer (IMPLEMENTER) | 0.72 | 0.78 | 0.71 | null | null | declining | 1 |
```

## Cross-Validation Flags Summary

```markdown
## Cross-Validation Flags

| Agent | Flag | Rule | Triggering Metrics |
|-------|------|------|--------------------|
| echelon-implementer (IMPLEMENTER) | high-terminology-low-accuracy | CV-2 | I-03=0.92, I-05=0.68 |
```
