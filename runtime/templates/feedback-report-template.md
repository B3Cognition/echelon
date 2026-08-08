# Feedback Report Template

Use this template for `{spec_dir}/feedback-report.md` for post-build self-assessment and final feedback. Keep predictions, outcomes, and conclusions traceable to source artifacts.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Produced by | `AUDITOR` |
| Build revision | `<commit / PR>` |
| Evidence reviewed | `<artifact list>` |

## Executive Summary

State the overall outcome, material misses, and the most important corrective action.

## Effort Accuracy

| Workstream | Estimated Human / AI | Actual Human / AI | Variance | Explanation |
| --- | --- | --- | --- | --- |
| `<workstream>` | `<estimate>` | `<actual>` | `<delta>` | `<evidence>` |

## Architecture Decision Outcomes

| Decision / ADR | Predicted Outcome | Actual Outcome | Evidence | Follow-up |
| --- | --- | --- | --- | --- |
| `<ADR>` | `<prediction>` | `<outcome>` | `<source>` | `<action>` |

## Requirements and Test Outcomes

| Area | Prediction | Actual | Gap / Result | Evidence |
| --- | --- | --- | --- | --- |
| `<area>` | `<prediction>` | `<outcome>` | `<gap>` | `<source>` |

## Critical Findings

| ID | Type | Severity | Finding | Recommended Expert |
| --- | --- | --- | --- | --- |
| `FB-NNN` | `<effort / architecture / requirement / risk / test>` | `<LOW/MEDIUM/HIGH/CRITICAL>` | `<finding>` | `<role>` |

## Auto-Feedback Summary

Use this section for BUILD finalization: record alignment severity, unmet intent points, remediation or escalation, and links to related artifacts.

## Actions and Learning

List owner, priority, closure criteria, and any KB proposal. Do not modify canonical KB files from this report.
