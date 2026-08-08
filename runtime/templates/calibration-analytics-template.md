# Calibration Analytics Template

Use this standalone template for `{spec_dir}/calibration-analytics.md`. Do not reuse only a section of the calibration dashboard; this artifact records the full analysis behind calibration decisions.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Produced by | `AUDITOR` |
| Calibration profile | `<path and version>` |
| Observation window | `<runs / dates>` |

## Domain Accuracy Analysis

| Domain | Samples | Accuracy | Correction Factor | Trend | Confidence |
| --- | ---: | ---: | ---: | --- | --- |
| `<domain>` | `<n>` | `<score>` | `<factor>` | `<improving / stable / declining>` | `<low / medium / high>` |

## Estimation Accuracy

| Work Type | Predicted | Actual | Variance | Calibration Implication |
| --- | ---: | ---: | ---: | --- |
| `<type>` | `<estimate>` | `<actual>` | `<delta>` | `<proposal>` |

## Confidence Distribution

| Band | Artifacts / Domains | Count | Action |
| --- | --- | ---: | --- |
| `<band>` | `<scope>` | `<n>` | `<action>` |

## Recommended Calibration Actions

List proposed correction changes, supporting data, expected effect, and whether a KB proposal was created. State cold-start limitations explicitly.
