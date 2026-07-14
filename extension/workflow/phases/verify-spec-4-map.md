# Phase: verify-spec-4-map
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-implementation-mapper

## Context Pack

Provide IMPLEMENTATION-MAPPER with:
- `{verify_run_dir}/canonical-requirements.json`
- `{verify_run_dir}/canonical-requirements.md`
- fulfillment checklist
- `{spec_dir}/deferred-scope.json` when present
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

If CodeGraph evidence was degraded and `codegraph-analysis.json` is absent, the
command writes skipped map artifacts and records
`codegraph_evidence_map: skipped_degraded_codegraph` in `state.json`. Do not
skip the command manually and do not hand-edit `state.json`.

If the command exits non-zero for any other reason, especially a missing
`requirement-audit.md`, `tasks.md`, or `codegraph-analysis.json`, hard stop with
BLOCKED. Do not hand-write missing upstream phase artifacts, do not inspect
Echelon or harness source code to infer file formats, and do not dispatch
IMPLEMENTATION-MAPPER until the required input exists.

## Dispatch Prompt

Map checklist items to concrete source, test, route, UI, configuration, and
CodeGraph evidence.

When `{spec_dir}/deferred-scope.json` has active entries, selected requirement
IDs are explicitly out of the current fulfillment scope. Do not manually
inspect those IDs or characterize them as deviations or gaps; the deterministic
judgment pre-pass owns their `DEFERRED_SCOPE` rows. Continue mapping every
remaining canonical requirement normally.

Use `{verify_run_dir}/canonical-requirements.json` as the row-set boundary.
Map only canonical IDs from that inventory. If source inspection reveals a
candidate item outside the inventory, record it separately as
`unmapped_candidate`; do not insert it as an implementation-map row.

Use `{verify_run_dir}/codegraph-evidence-map.json` as the primary mapping input.
Preserve deterministic rows only together with their `evidence_kind`,
`evidence_strength`, `runtime_threshold`, and `confidence` fields. A row with
`evidence_kind=assertion_only` is not full implementation evidence for runtime
threshold requirements even when source and tests exist; keep it in the fallback
queue for SPEC-GUARD review. Preserve `high` and `medium` deterministic rows
unless the cited source/test evidence is directly contradictory. Treat
`summary.fallback_requirement_ids` as the bounded fallback queue for manual
inspection. Inspect source/tests only for IDs in that queue, plus the cited
files/symbols/tests of a `high` or `medium` deterministic row that appears
contradictory. Do not inspect outside that queue or cited evidence set.

Distinguish source evidence from executable test evidence and measured
CI/runtime artifacts. Do not rewrite assertion-gate functions or synthetic
fixture tests as measured runtime evidence.

## Expected Output

- `{verify_run_dir}/implementation-map.md` with exactly this parser-conformant
  9-column table schema:

```markdown
| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |
|----|-------------------------|---------------|--------------------|---------------|-------------------|-------------------|------------|-------|
| FR-001 | src/file.ts:function | tests/file.test.ts::case | module.symbol | source_and_test | strong | false | high | ... |
```

- `Evidence Kind` must be one of `source_and_test`, `source_only`,
  `test_only`, `measured_runtime`, `assertion_only`, `missing`, or `meta`.
- `Evidence Strength` must be `strong`, `medium`, `weak`, or `none`; do not write `source_and_test_strong` in `Evidence Strength`. Use `Evidence Kind=source_and_test` plus `Evidence Strength=strong` instead.
- `Runtime Threshold` must be literal `true` or `false`.
- `Confidence` must be `high`, `medium`, `low`, or `none`.
- Do not inspect Echelon source code to discover this schema; this phase
  contract is authoritative.
- separate `unmapped_candidate` notes for any candidate row not present in
  `{verify_run_dir}/canonical-requirements.json`.
- `{verify_run_dir}/codegraph-evidence-map.json`
- `{verify_run_dir}/codegraph-evidence-map.md`

Proceed to `verify-spec-5-judge`.
