# Prompt Version Observations Template

Use this template for `{spec_dir}/prompt-version-observations.md` to record correlations between prompt versions and quality signals. Observations are not causal conclusions.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Produced by | `AUDITOR` |
| Observation window | `<runs and dates>` |
| Sample caveat | `<sample size / confounders>` |

## Observations

| Agent | Domain | Prompt Version | Accuracy Signal | Downstream Outcome | Evidence |
| --- | --- | --- | --- | --- | --- |
| `<agent>` | `<domain>` | `<version or hash>` | `<score / correction>` | `<result>` | `<run IDs or artifacts>` |

## Correlation Analysis

Describe observed association, sample size, confounders, and what would be required to establish causation.

## Next Experiment

Propose a bounded comparison or explicitly state that evidence is insufficient for a prompt change.
