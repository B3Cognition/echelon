# Phase: verify-spec-2-codegraph
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Objective

Refresh structural evidence for the current source tree. Do not reuse stale
brownfield RE artifacts.

## Instructions

Run the existing RE CodeGraph bridge against the current project root.

Write:
- `{verify_run_dir}/codegraph-analysis.json`
- `{verify_run_dir}/codegraph-summary.json`

If CodeGraph fails, write `{verify_run_dir}/codegraph-error.txt` and continue
with `structural_evidence: degraded`.

## Output

Proceed to `verify-spec-3-audit`.
