# Phase: verify-spec-4-map
# Read by: echelon.commander (COMMANDER)
# Agent: echelon.implementation-mapper

## Context Pack

Provide IMPLEMENTATION-MAPPER with:
- `{verify_run_dir}/canonical-requirements.json`
- `{verify_run_dir}/canonical-requirements.md`
- `{verify_run_dir}/product-inventory.json`
- `{verify_run_dir}/product-inventory.md`
- fulfillment checklist
- `{spec_dir}/deferred-scope.json` when present
- current source tree and tests
- verification `state.json`
- `{verify_run_dir}/codegraph-summary.json`
- `{verify_run_dir}/codegraph-analysis.json`
- `{verify_run_dir}/perlgraph-summary.json`
- `{verify_run_dir}/perlgraph-analysis.json`
- `{verify_run_dir}/codegraph-evidence-map.json`
- `{verify_run_dir}/codegraph-evidence-map.md`
- `{verify_run_dir}/coverage-evidence.json`
- `{verify_run_dir}/coverage-evidence.md`

## Deterministic Pre-map

Before dispatching IMPLEMENTATION-MAPPER, run:

```bash
python -m harness write-coverage-evidence \
  "{spec_dir}" \
  "{verify_run_dir}"
python -m harness write-codegraph-evidence-map \
  "{verify_run_dir}/requirement-audit.md" \
  "{verify_run_dir}/codegraph-analysis.json" \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/codegraph-evidence-map.json" \
  "{verify_run_dir}/codegraph-evidence-map.md" \
  "{spec_dir}/coverage-map.md"
```

The coverage-evidence command is Python-owned reconciliation of the current
coverage map, canonical inventory, task progress, and owner-controlled
deferrals. If it exits non-zero, hard stop with BLOCKED. A candidate declaration
of `strong` test evidence cannot override its deferred, escalated, missing, or
contradictory rows.

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

Map checklist items to concrete source, test, route, UI, configuration,
CodeGraph evidence, and PerlGraph evidence for Perl source.

Use `{verify_run_dir}/product-inventory.json` as the authoritative product-file
boundary for repository-wide existence and cardinality claims. Its `.echelon`,
`.git`, and `.harness-build-status.json` exclusions are Python-owned: do not add
deployed control-plane files back into product counts. Cite the inventory entry
or basename count together with direct file inspection. Inventory membership is
not behavioral fulfillment proof; behavior still requires verified source,
executable test, or measured runtime evidence.

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
Copy deterministic `codegraph_candidates` into the implementation map as
candidate evidence only, together with each row's `evidence_kind`,
`evidence_strength`, `runtime_threshold`, and `confidence` fields. A row with
`evidence_kind=assertion_only` is not full implementation evidence for runtime
threshold requirements even when source and tests exist; keep it in the fallback
queue for SPEC-GUARD review.

Treat `summary.fallback_requirement_ids` as the bounded fallback queue for
manual inspection. Inspect source/tests for IDs in that queue, for IDs whose
CodeGraph candidates are empty, and for cited files/symbols/tests of a
`high` or `medium` candidate row that appears contradictory. Do not inspect
outside that queue. Do not inspect outside that queue or cited evidence set.

Do not dismiss CodeGraph evidence as useless when its cited symbols are generic,
term-matched, low-confidence, or contradictory-looking. CodeGraph rows are
candidate structural leads, not fulfillment proof; fallback inspection refines
CodeGraph candidates and does not replace or ignore them. Manual source/test
citations must go only into the Verified Implementation Evidence and Verified
Test Evidence cells. CodeGraph candidates must stay in the CodeGraph Candidates
cell, with Candidate Disposition set to `accepted`, `candidate_only`,
`contradicted`, `unrelated`, or `none` based on direct inspection. When
CodeGraph has no evidence for a requirement, use source/test inspection to fill
verified evidence and leave CodeGraph Candidates blank with
Candidate Disposition `none`.

Use `{verify_run_dir}/perlgraph-summary.json` and
`{verify_run_dir}/perlgraph-analysis.json` as additional structural evidence for
Perl source files. PerlGraph module, package, sub, method, and call edges may
support the same implementation-map row when they cite concrete project files.
Treat low-confidence or dynamic PerlGraph edges as uncertainty evidence, not
proof of fulfillment, and keep affected IDs in the bounded fallback queue unless
source and executable test evidence independently satisfy the requirement.
Treat PerlGraph `unsupported_patterns` as source-backed notes about dynamic Perl
behavior and candidate future PerlGraph improvements. They may explain why a
row needs manual judgment, but they must not be converted into fulfilled
implementation evidence by themselves.

Distinguish source evidence from executable test evidence and measured
CI/runtime artifacts. Do not rewrite assertion-gate functions or synthetic
fixture tests as measured runtime evidence.

Read `coverage-evidence.json` before assigning verified test evidence. Never
label a requirement's evidence strong when its deterministic coverage status is
not `automated` or `owner_deferred`. Record the contradiction in Notes so the
judgment pre-pass can route repair.

## Expected Output

- `{verify_run_dir}/implementation-map.md` with `schema_version: 2` and exactly
  this parser-conformant 10-column table schema:

```markdown
schema_version: 2

| ID | Verified Implementation Evidence | Verified Test Evidence | CodeGraph Candidates | Candidate Disposition | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |
|----|----------------------------------|------------------------|----------------------|-----------------------|---------------|-------------------|-------------------|------------|-------|
| FR-001 | src/file.ts:function | tests/file.test.ts::case | module.symbol | accepted | source_and_test | strong | false | high | ... |
```

- Verified evidence cells must cite direct source/test inspection. Do not copy
  CodeGraph candidates into them unless the cited files/symbols were inspected
  and verified.
- CodeGraph Candidates is a deterministic lead/audit column, not fulfillment
  proof by itself.
- Candidate Disposition must be one of `accepted`, `candidate_only`,
  `contradicted`, `unrelated`, or `none`.
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
