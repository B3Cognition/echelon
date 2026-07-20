# Regression Alerts Template

Use this template for `{spec_dir}/regression-alerts.md` only when a material regression is detected. Omit the artifact when no regression exists.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Produced by | `ADAPTIVE` |
| Comparison baseline | `<prior run>` |
| Detection threshold | `<configured rule>` |

## Regression Alerts

| Area | Previous | Current | Delta | Severity | Probable Cause | Owner |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `<area>` | `<value>` | `<value>` | `<delta>` | `<LOW/MEDIUM/HIGH/CRITICAL>` | `<hypothesis or unknown>` | `<role>` |

## Containment and Verification

For each alert, give the immediate containment action, the recovery criterion, and the evidence required to close it.

## Routing

State escalation and priority. Do not silently downgrade a regression because its cause is uncertain.
