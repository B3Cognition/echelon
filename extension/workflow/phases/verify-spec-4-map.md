# Phase: verify-spec-4-map
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-implementation-mapper

## Context Pack

Provide IMPLEMENTATION-MAPPER with:
- fulfillment checklist
- current source tree and tests
- verification `state.json`
- `{verify_run_dir}/codegraph-summary.json`
- `{verify_run_dir}/codegraph-analysis.json`
- `{verify_run_dir}/codegraph-evidence-map.json`
- `{verify_run_dir}/codegraph-evidence-map.md`

## Deterministic Pre-map

Before dispatching IMPLEMENTATION-MAPPER, run:

```bash
python -m harness write-codegraph-evidence-map \
  "{verify_run_dir}/requirement-audit.md" \
  "{verify_run_dir}/codegraph-analysis.json" \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/codegraph-evidence-map.json" \
  "{verify_run_dir}/codegraph-evidence-map.md" \
  "{spec_dir}/coverage-map.md"
```

If `{spec_dir}/coverage-map.md` is absent, rerun the same command without the
final coverage-map argument.

If CodeGraph evidence was degraded and `codegraph-analysis.json` is absent, skip
the pre-map, record `codegraph_evidence_map: skipped_degraded_codegraph` in
`state.json`, and tell IMPLEMENTATION-MAPPER to perform the previous manual
mapping path.

## Dispatch Prompt

Map checklist items to concrete source, test, route, UI, configuration, and
CodeGraph evidence.

Use `{verify_run_dir}/codegraph-evidence-map.json` as the primary mapping input.
Preserve `high` and `medium` deterministic rows unless direct source inspection
contradicts them. Only perform broad LLM/source exploration for rows with
`confidence` of `low`, `none`, or `ambiguous`, plus any row whose deterministic
evidence is contradicted by source inspection. Treat
`summary.fallback_requirement_ids` as the bounded fallback queue; do not inspect
outside that queue except to validate a cited high/medium row that appears
contradictory.

Distinguish source evidence from executable test evidence.

## Expected Output

- evidence map per requirement.
- `{verify_run_dir}/codegraph-evidence-map.json`
- `{verify_run_dir}/codegraph-evidence-map.md`

Proceed to `verify-spec-5-judge`.
