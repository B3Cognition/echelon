# Knowledge Base Schema (Tier 1)

## Scope

This file is the authoritative schema contract for Tier 1 knowledge-base files:

1. `calibration-profile.yaml`
2. `estimates-log.yaml`
3. `patterns.yaml`
4. `pitfalls.yaml`
5. `agent-scores.yaml`

Schema version for Tier 1 is `1` for all files.

## Global Rules

1. Every file must have top-level `schema_version: 1`.
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
