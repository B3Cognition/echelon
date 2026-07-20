# Stagnation Flags Template

Use this template for `{spec_dir}/stagnation-flags.md` only when evidence shows progress has stalled. Omit the artifact when no stagnation signal is present.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Produced by | `ADAPTIVE` |
| Detection window | `<runs or iterations>` |
| Threshold | `<configured rule>` |

## Stagnation Signals

| Signal | Evidence | Duration | Impact | Recommended Experiment |
| --- | --- | --- | --- | --- |
| `<signal>` | `<scores, diffs, or repetition>` | `<runs>` | `<affected quality or delivery>` | `<bounded experiment>` |

## Hypotheses

List plausible causes separately from confirmed facts, with evidence that could disprove each hypothesis.

## Routing

State whether to summon INNOVATE, seek human input, or continue observation, and why.
