# SAGE Contradiction Detection Reference

Load this appendix during SAGE spec-validation Step 8.

## Contradiction Types

Check these five contradiction types:

1. `requirement_conflict`: two `FR-*` requirements cannot both be satisfied. Example: one requirement says all data is encrypted at rest while another requires plaintext search indexes.
2. `assumption_requirement_misalignment`: `assumptions.md` states one condition while `spec.md` requires behavior that contradicts it.
3. `boundary_violation`: `spec.md` requires behavior that `boundaries.md` explicitly declares out of scope.
4. `priority_inversion`: a P0 requirement depends on a P2 requirement that may not be implemented.
5. `acceptance_criteria_conflict`: Given/When/Then blocks describe contradictory outcomes for overlapping conditions.

## Report Format

For each contradiction found, produce:

| Field | Description |
| --- | --- |
| `contradiction_type` | One of the five contradiction types above |
| `artifact_a` | First artifact with filename and section/ID |
| `artifact_b` | Second artifact with filename and section/ID |
| `description` | Plain-language description of the contradiction |
| `severity` | `BLOCKING` or `WARNING` |
| `suggested_resolution` | Concrete action to resolve the contradiction |

## Zero-Contradiction Statement

When zero contradictions are found, include:

```text
No contradictions detected across [N] artifacts ([list artifact filenames]).
Contradiction types checked: requirement_conflict, assumption_requirement_misalignment, boundary_violation, priority_inversion, acceptance_criteria_conflict.
```

## Logging Requirement

Always log that the contradiction check was performed, including:

- number of artifacts scanned
- contradiction count, including zero
- contradiction types checked

Put the entry in `issues.md` and return it in the `echelon_result` block.
