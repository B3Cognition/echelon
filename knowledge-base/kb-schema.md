# Knowledge Base Schema

## Scope

This file is the authoritative schema contract for all knowledge-base files:

Tier 1 files (schema version 1):

1. `calibration-profile.yaml`
2. `estimates-log.yaml`
3. `patterns.yaml`
4. `pitfalls.yaml`
5. `agent-scores.yaml`

Tier 2 files (schema version 2):

6. `internalization-log.yaml`
7. `evolution-signals.yaml`

## Global Rules

1. Every file must have top-level `schema_version` matching the version specified in this document.
2. All timestamps must be ISO-8601 date-time unless explicitly noted as date-only.
3. Historical logs are append-only where marked by `append_only: true`.
4. Every write operation must carry provenance (`run_id`, `source`, `created_at`).
5. Queue records in `knowledge-base/.pending/` must match the model in this document and `specs/001-cognitive-squad-improvements/data-model.md`.

## calibration-profile.yaml

Required top-level keys:

1. `schema_version` (integer, required)
2. `last_updated` (string date-time, required)
3. `confidence_policy` (object, required)
4. `domains` (map/object, required)

`confidence_policy` required keys:

1. `validation_run_count` (integer, required)
2. `low_confidence_threshold` (number between 0 and 1, required)
3. `correction_factor_min` (number, required)
4. `correction_factor_max` (number, required)

`domains.<domain_id>` required keys:

1. `accuracy` (number between 0 and 1)
2. `sample_size` (integer)
3. `trend` (enum: `stable` | `improving` | `declining`)
4. `correction_factor` (number between 0.5 and 3.0)
5. `last_updated` (date string)
6. `source` (string)
7. `status` (enum: `validation` | `production`)

Minimum-valid example:

```yaml
schema_version: 1
last_updated: 2026-03-19T00:00:00Z
confidence_policy:
 validation_run_count: 20
 low_confidence_threshold: 0.6
 correction_factor_min: 0.5
 correction_factor_max: 3.0
domains:
 cognitive-squad:
  accuracy: 0.75
  sample_size: 20
  trend: stable
  correction_factor: 1.0
  last_updated: 2026-03-19
  source: seed
  status: validation
```

## estimates-log.yaml

Required top-level keys:

1. `schema_version` (integer, required)
2. `append_only` (boolean, required and must be `true`)
3. `entries` (array, required)

`entries[]` required keys:

1. `id` (string)
2. `run_id` (string)
3. `created_at` (string date-time)
4. `agent` (string)
5. `domain` (string)
6. `estimate_hours` (number)
7. `actual_hours` (number or null)
8. `delta_hours` (number or null)
9. `confidence` (number between 0 and 1)
10. `source` (string)

Minimum-valid example:

```yaml
schema_version: 1
append_only: true
entries:
 - id: est-001
  run_id: squad-001-1742401234
  created_at: 2026-03-19T00:00:00Z
  agent: AUDITOR
  domain: cognitive-squad
  estimate_hours: 4
  actual_hours: null
  delta_hours: null
  confidence: 0.7
  source: seeded
```

## patterns.yaml

Required top-level keys:

1. `schema_version` (integer, required)
2. `entries` (array, required)

`entries[]` required keys:

1. `id` (string)
2. `source` (string)
3. `created_at` (string date-time)
4. `confidence` (number between 0 and 1)
5. `run_id` (string)

Optional keys:

1. `name` (string)
2. `description` (string)
3. `status` (string)

Minimum-valid example:

```yaml
schema_version: 1
entries:
 - id: pat-001
  source: seed
  created_at: 2026-03-19T00:00:00Z
  confidence: 0.8
  run_id: squad-001-1742401234
```

## pitfalls.yaml

Required top-level keys:

1. `schema_version` (integer, required)
2. `entries` (array, required)

`entries[]` required keys:

1. `id` (string)
2. `source` (string)
3. `created_at` (string date-time)
4. `confidence` (number between 0 and 1)
5. `run_id` (string)

Optional keys:

1. `name` (string)
2. `description` (string)
3. `status` (string)

Minimum-valid example:

```yaml
schema_version: 1
entries:
 - id: pit-001
  source: seed
  created_at: 2026-03-19T00:00:00Z
  confidence: 0.6
  run_id: squad-001-1742401234
```

## agent-scores.yaml

Tier 1 introduces no structure change. Existing structure is documented for forward compatibility.

Required top-level keys:

1. `schema_version` (integer, required)
2. `agents` (map, required)

Minimum-valid example:

```yaml
schema_version: 1
agents:
 commander:
  history:
   - run_id: squad-001-1742401234
    score: 0.8
    created_at: 2026-03-19T00:00:00Z
```

## internalization-log.yaml

Schema version: `2`

Required top-level keys:

1. `schema_version` (integer, required — must be `2`)
2. `append_only` (boolean, required — must be `true`)
3. `entries` (array, required)

`entries[]` required keys:

1. `id` (string, pattern: `int-NNN`)
2. `run_id` (string, must match existing run ID)
3. `source` (string, always `"AUDITOR"`)
4. `created_at` (string ISO-8601 date-time)
5. `agent` (string, must match agents.yaml codename)
6. `agent_tier` (string, enum: `deep` | `moderate` | `minimal` | `exempt`)
7. `prompt_version` (string, must match prompt-versions.yaml)
8. `int_I01_requirement_coverage_rate` (number 0.0-1.0 or null)
9. `int_I02_constraint_adherence_score` (number 0.0-1.0 or null)
10. `int_I03_terminology_fidelity` (number 0.0-1.0 or null)
11. `int_I04_dependency_awareness` (number 0.0-1.0 or null)
12. `int_I05_numeric_contradiction_rate` (number 0.0-1.0 or null)
13. `int_I06_uncited_decision_rate` (number 0.0-1.0 or null)
14. `int_I07_cross_reference_accuracy` (number 0.0-1.0 or null)
15. `int_I08_keyword_scope_rate` (number 0.0-1.0 or null)
16. `int_I09_confidence_accuracy` (number 0.0-1.0 or null)
17. `int_I10_doubt_signal_quality` (number 0.0-1.0 or null)
18. `int_I11_blind_spot_rate` (number 0.0-1.0 or null)
19. `int_I12_escalation_precision` (number 0.0-1.0 or null)
20. `int_I13_first_pass_acceptance` (number 0.0-1.0 or null)
21. `int_I14_rework_severity` (number 0.0-1.0 or null)
22. `int_I15_explicit_decision_traceability` (number 0.0-1.0 or null)
23. `int_I16_priority_alignment` (number 0.0-1.0 or null)
24. `int_absorption_score` (number 0.0-1.0 or null — mean of I-01..I-04 excluding nulls)
25. `int_accuracy_score` (number 0.0-1.0 or null — mean of I-05..I-08 excluding nulls)
26. `int_calibration_score` (number 0.0-1.0 or null — mean of I-09..I-12 excluding nulls)
27. `int_transfer_score` (number 0.0-1.0 or null — mean of I-13..I-16 excluding nulls)
28. `int_gate_verdict` (string, enum: `PASS` | `FAIL` | `EXEMPT` | `INSUFFICIENT_DATA`)
29. `chk_doubt_count` (integer, >= 0)
30. `computation_health` (object, see sub-schema below)

`entries[]` optional keys:

1. `chk_score` (integer 0-6 or null — CHECKPOINT self-reported score)
2. `chk_doubt_categories` (array of strings, enum per item: `role` | `constraints` | `architecture` | `domain` | `tasks` | `doubts`)
3. `chk_doubt_resolution_types` (array of strings, enum per item: `artifact_read` | `clarification` | `escalation` | `deferred`)
4. `downstream_outcome` (string or null, enum: `passed` | `rework_spec` | `rework_code` | `rework_test` | null — backfilled during Mode 3 Step 4)
5. `downstream_agent` (string or null — agent codename that triggered rework)
6. `cross_validation_flags` (array of strings, enum per item: `citation-stuffing` | `superficial-vocabulary-matching` | `rote-id-copying`)
7. `disagreement_flag` (string or null — `metrics-pass-doubts-high` or null)
8. `run_type` (string — `validation_run` for first 20 runs)

`computation_health` sub-schema required keys:

1. `inputs_available` (integer — count of metrics with all inputs available)
2. `inputs_missing` (integer — count of metrics with missing inputs)
3. `formulas_valid` (integer — count of metrics that produced valid results)
4. `formulas_failed` (integer — count of metrics that failed, yielding null)

`computation_health` optional keys:

1. `failure_reasons` (array of objects `{metric_id, reason}` — reasons for failed computations)

Null vs Zero Distinction:

- `null` means the metric could not be computed (missing inputs, insufficient data, or cold-start). It is excluded from category score aggregation.
- `0` (zero) means the metric was computed and the agent scored the worst possible value. Zero IS included in category score aggregation.
- `0.0` and `null` are semantically different and must never be conflated.

Validation Rules:

1. Immediate metrics (I-01 to I-08) must NOT be null when spec and agent artifacts are available
2. Deferred metrics (I-09 to I-16) MAY be null with reason recorded in `computation_health.failure_reasons`
3. Category scores exclude null constituent metrics from mean; if all constituents are null the category score is null
4. `int_gate_verdict` is `EXEMPT` only for agents in the `exempt` tier (COMMANDER)
5. `int_gate_verdict` is `INSUFFICIENT_DATA` only when all gate metrics are null
6. All metric values must be 0.0-1.0 or null (no out-of-range values)
7. `downstream_outcome` is null at creation, backfilled later

Minimum-valid example:

```yaml
schema_version: 2
append_only: true
entries:
  - id: int-001
    run_id: squad-003-1742652000
    source: AUDITOR
    created_at: 2026-03-22T13:00:00Z
    agent: IMPLEMENTER
    agent_tier: deep
    prompt_version: v1.0.0
    int_I01_requirement_coverage_rate: 0.85
    int_I02_constraint_adherence_score: 0.90
    int_I03_terminology_fidelity: 0.72
    int_I04_dependency_awareness: 0.80
    int_I05_numeric_contradiction_rate: 0.95
    int_I06_uncited_decision_rate: 0.88
    int_I07_cross_reference_accuracy: 0.92
    int_I08_keyword_scope_rate: 0.78
    int_I09_confidence_accuracy: null
    int_I10_doubt_signal_quality: null
    int_I11_blind_spot_rate: null
    int_I12_escalation_precision: null
    int_I13_first_pass_acceptance: null
    int_I14_rework_severity: null
    int_I15_explicit_decision_traceability: null
    int_I16_priority_alignment: null
    int_absorption_score: 0.8175
    int_accuracy_score: 0.8825
    int_calibration_score: null
    int_transfer_score: null
    int_gate_verdict: PASS
    chk_score: 6
    chk_doubt_count: 0
    chk_doubt_categories: []
    chk_doubt_resolution_types: []
    downstream_outcome: null
    downstream_agent: null
    cross_validation_flags: []
    disagreement_flag: null
    computation_health:
      inputs_available: 8
      inputs_missing: 8
      formulas_valid: 8
      formulas_failed: 0
      failure_reasons: []
    run_type: validation_run
```

## evolution-signals.yaml

Schema version: `2`

Required top-level keys:

1. `schema_version` (integer, required — must be `2`)
2. `append_only` (boolean, required — must be `true`)
3. `signals` (array, required)

`signals[]` required keys:

1. `id` (string, pattern: `evo-sig-NNN`)
2. `run_id` (string — run that detected the signal)
3. `source` (string, always `"AUDITOR"`)
4. `created_at` (string ISO-8601 date-time)
5. `trigger` (string, enum: `regression_detected` | `declining_trend` | `recurring_pitfall` | `recurring_rejection` | `int_declining_trend` | `int_recurring_failure` | `int_accuracy_drop`)
6. `severity` (string, enum: `LOW` | `MEDIUM` | `HIGH` | `CRITICAL`)
7. `affected_agents` (array of strings — agent codenames)
8. `affected_metrics` (array of strings — metric IDs, e.g. `I-05`, `I-07`)
9. `run_ids` (array of strings — at least 3 entries constituting the trend)
10. `prompt_version` (string — prompt version at time of detection)
11. `metrics` (object — signal-specific data such as accuracy deltas)
12. `failure_analysis` (string — root cause analysis)
13. `status` (string, enum: `open` | `acknowledged` | `proposal_created` | `resolved` | `wont_fix`)

`signals[]` optional keys:

1. `review_timestamp` (string ISO-8601 or null — when COMMANDER acknowledged)
2. `proposal_artifact_ref` (string or null — path to ADAPTIVE's proposal artifact)
3. `resolution_reason` (string or null — why signal was resolved or won't-fixed)

Internalization-Specific Triggers:

- `int_declining_trend`: category score declined over N consecutive runs (N >= `min_consecutive_runs` from config)
- `int_recurring_failure`: same metric(s) failed gate threshold across multiple runs
- `int_accuracy_drop`: sudden single-run drop in int-Accuracy category exceeding severity threshold

Severity Mapping (internalization-specific):

| Decline Magnitude | Severity |
|-------------------|----------|
| 0.10 - 0.19 | LOW |
| 0.20 - 0.29 | MEDIUM |
| 0.30 - 0.39 | HIGH |
| >= 0.40 | CRITICAL |

Lifecycle State Transitions:

```
  open ──[COMMANDER reviews]──> acknowledged
  acknowledged ──[ADAPTIVE proposes]──> proposal_created
  proposal_created ──[proposal accepted]──> resolved
  proposal_created ──[proposal rejected]──> wont_fix
```

Guard Conditions:

1. `open -> acknowledged`: COMMANDER reviews the signal during squad report generation
2. `acknowledged -> proposal_created`: ADAPTIVE produces a proposal artifact and sets `proposal_artifact_ref`
3. `proposal_created -> resolved`: COMMANDER accepts and applies the proposal; `resolution_reason` must be set
4. `proposal_created -> wont_fix`: COMMANDER rejects the proposal; `resolution_reason` must explain why

Minimum-valid example:

```yaml
schema_version: 2
append_only: true
signals:
  - id: evo-sig-001
    run_id: squad-003-1742652000
    source: AUDITOR
    created_at: 2026-03-22T13:30:00Z
    trigger: int_declining_trend
    severity: MEDIUM
    affected_agents: [IMPLEMENTER]
    affected_metrics: [I-05, I-07]
    run_ids: [squad-001, squad-002, squad-003]
    prompt_version: v1.0.0
    metrics:
      current_int_accuracy: 0.62
      peak_int_accuracy: 0.85
      decline_delta: 0.23
      sample_size: 3
    failure_analysis: "IMPLEMENTER int-Accuracy declined 0.23 over 3 consecutive runs."
    status: open
    review_timestamp: null
    proposal_artifact_ref: null
    resolution_reason: null
```

## Pending Queue Structure (Alignment Requirement)

Queue files in `knowledge-base/.pending/` must include:

1. `schema_version` (integer)
2. `operation_id` (string)
3. `created_at` (string date-time)
4. `source` (object with required `run_id` and `agent`)
5. `target_file` (string)
6. `operation` (string; Tier 1 uses `append_entry`)
7. `payload` (object)
8. `checksum` (string prefixed with `sha256:`)

Minimum-valid example:

```yaml
schema_version: 1
operation_id: op-20260319-0001
created_at: 2026-03-19T20:10:30Z
source:
 run_id: squad-001-1742401234
 agent: AUDITOR
target_file: knowledge-base/estimates-log.yaml
operation: append_entry
payload:
 id: est-20260319-0001
 run_id: squad-001-1742401234
 created_at: 2026-03-19T20:10:30Z
 domain: fallback
 estimate_hours: 5
 confidence: 0.6
checksum: sha256:REQUIRED
```
