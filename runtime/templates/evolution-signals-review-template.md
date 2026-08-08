# Evolution Signals Review Template

Use this template for `{spec_dir}/evolution-signals-review.md` when AUDITOR detects a qualified evolution signal. Keep each signal run-local and propose, rather than directly mutate, any canonical KB update.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Produced by | `AUDITOR` |
| Signal threshold | `<configuration>` |
| Sample basis | `<n and source>` |

## Signal Review

| ID | Trigger | Severity | Metrics | Failure Analysis | Status |
| --- | --- | --- | --- | --- | --- |
| `evo-sig-NNN` | `<trigger>` | `<LOW/MEDIUM/HIGH/CRITICAL>` | `<scores and deltas>` | `<known cause or hypothesis>` | `<open / monitored / resolved>` |

## Signal Detail: evo-sig-NNN

- **Evidence:** `<linked artifacts, run IDs, and sample size>`
- **Threshold rationale:** `<why it fired>`
- **Counter-evidence / caveats:** `<limits>`
- **Recommended action:** `<investigate, calibrate, or human review>`
- **KB proposal:** `<path or none>`

## Lifecycle Review

Record state transitions and closure evidence. Do not mark a signal resolved without evidence.
