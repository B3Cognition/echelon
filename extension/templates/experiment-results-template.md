# Experiment Results Template

Use this template for `{spec_dir}/experiment-results.md` whenever INVESTIGATOR runs a prototype or measurement spike. The artifact is Markdown; journal entries must reference `experiment-results.md`, never a JSON filename.

## Metadata

| Field | Value |
| --- | --- |
| Experiment ID | `EXP-NNN` |
| Spec / run | `<spec-id> / <run-id>` |
| Investigator | `INVESTIGATOR` |
| Started / completed | `<timestamps>` |
| Environment / revision | `<environment and commit>` |

## Experiment

- **Question:** `<decision this experiment informs>`
- **Hypothesis:** `<falsifiable prediction>`
- **Falsifier:** `<result that would disprove it>`
- **Method and controls:** `<procedure, control, and variables>`

## Results

| Metric | Expected | Observed | Sample Size | Result |
| --- | --- | --- | ---: | --- |
| `<metric>` | `<prediction>` | `<measurement>` | `<n>` | `<supports / refutes / inconclusive>` |

## Evidence

| Evidence | Location / Command | Reproducibility Notes |
| --- | --- | --- |
| `<log, benchmark, or fixture>` | `<path or command>` | `<how to reproduce>` |

## Interpretation

State what the measurements establish, what remains unknown, and the resulting recommendation. Do not generalize beyond the measured environment.

## Follow-up

List the next experiment or explicitly state that none is required.
