# Confidence Flags Template

Use this template for `{spec_dir}/confidence-flags.md`. Report calibrated confidence for the current run; do not hide low-confidence results.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Produced by | `AUDITOR` |
| Calibration profile | `<path and version>` |
| Sample basis | `<historical samples / cold-start>` |

## Confidence Flags

| Artifact | Domains | Confidence | Correction Applied | Risk | Action |
| --- | --- | ---: | --- | --- | --- |
| `<artifact>` | `<domain(s)>` | `<0.00-1.00>` | `<factor or none>` | `<LOW/MEDIUM/HIGH>` | `<accept, investigate, or human review>` |

## Calculation Evidence

| Artifact | Calibration Inputs | Sample Size | Method / Reference | Caveats |
| --- | --- | ---: | --- | --- |
| `<artifact>` | `<inputs>` | `<n>` | `<calculation>` | `<limits>` |

## Escalations

List every item requiring investigation or human review, including the threshold that triggered it. State `None` when no escalation is needed.

## Audit Notes

Record missing history, cold-start assumptions, and any correction that could not be applied.
