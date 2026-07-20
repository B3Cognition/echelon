# Drift Escalation Template

Use this template for `{spec_dir}/drift-escalation.md` only for `MAJOR_DRIFT` in banzai mode. This artifact requests a human decision before completion; it does not authorize autonomous rework.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Severity | `MAJOR_DRIFT` |
| Autonomy mode | `banzai` |
| Alignment source | `intent-alignment-final.md` |

## Drift Summary

State the intended outcome, the observed divergence, and why the configured threshold was crossed.

| Divergence | Expected | Observed | Impact | Evidence |
| --- | --- | --- | --- | --- |
| `<unmet intent point>` | `<intended outcome>` | `<actual outcome>` | `<user / product impact>` | `<artifact or test>` |

## Required Human Decision

State the decision required: approve bounded rework, accept the divergence, revise intent, or stop the release. Include the owner and deadline/next checkpoint if known.

## Containment

List release constraints, safe next actions, and information needed to resolve the escalation.
