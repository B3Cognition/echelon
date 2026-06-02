# Phase: verify-spec-4-map
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-implementation-mapper

## Context Pack

Provide IMPLEMENTATION-MAPPER with:
- fulfillment checklist
- current source tree and tests
- verification `state.json`
- `{verify_run_dir}/codegraph-summary.json`
- `{verify_run_dir}/codegraph-analysis.json` only when symbol-level detail is needed

## Dispatch Prompt

Map checklist items to concrete source, test, route, UI, configuration, and
CodeGraph evidence. Distinguish source evidence from executable test evidence.

## Expected Output

- evidence map per requirement.

Proceed to `verify-spec-5-judge`.
