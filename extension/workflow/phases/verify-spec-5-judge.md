# Phase: verify-spec-5-judge
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-spec-guard

## Context Pack

Provide SPEC-GUARD with:
- `{verify_run_dir}/canonical-requirements.json`
- `{verify_run_dir}/canonical-requirements.md`
- `{verify_run_dir}/requirement-audit.md`
- `{verify_run_dir}/judgment-prepass.json`
- `{verify_run_dir}/judgment-prepass.md`
- fulfillment checklist
- implementation evidence map
- `spec.md`
- `tasks.md`
- `progress-integrity.json`
- `progress-integrity.md`
- verification `state.json`

## Deterministic Pre-judge

Before dispatching SPEC-GUARD, run:

```bash
python -m harness write-judgment-prepass "{spec_dir}" "{verify_run_dir}"
```

This writes `{verify_run_dir}/judgment-prepass.json` and
`{verify_run_dir}/judgment-prepass.md`.

If `fallback_ids` in `judgment-prepass.json` is empty, skip SPEC-GUARD and
assemble the final report directly with:

```bash
python -m harness assemble-fulfillment-report \
  "{verify_run_dir}/canonical-requirements.json" \
  "{verify_run_dir}/judgment-prepass.json" \
  "{spec_dir}/fulfillment-report.md" \
  "{spec_dir}/fulfillment-report.md" \
  "{verify_run_dir}/state.json"
```

Then proceed directly to row-set integrity validation and summary.

## Dispatch Prompt

Run SPEC-GUARD in fulfillment mode. Assign exactly one status per item:
`IMPLEMENTED`, `PARTIAL`, `UNVERIFIED`, `MISSING`, `DEVIATED`, or
`OBSOLETE_SPEC`.

Python owns mechanical judgments and the final report row set. SPEC-GUARD must
judge only IDs listed in `fallback_ids` from `judgment-prepass.json`.
SPEC-GUARD must not emit rows for mechanically decided IDs.

Use `{verify_run_dir}/canonical-requirements.json` as the only allowed
requirement row set. Judge every canonical ID exactly once. Do not add report
rows for IDs outside the inventory; record such discoveries separately as
`unmapped_candidate` notes.

When `verify_scope=scoped` in `state.json`, the scoped report boundary is strict:
judge only IDs listed in `scoped_ids`. Within that boundary, SPEC-GUARD must
manually judge only unresolved IDs also listed in `fallback_ids`; mechanically
decided scoped IDs are carried by Ralph. The scoped output may contain rows for
`scoped_ids` only; Ralph will merge those rows over the last full fulfillment
report and preserve unaffected rows. Include `base_full_verify_commit` in the
scoped run summary so the harness can prove which full report the scoped
judgment extends. Do not summarize a scoped run as a replacement for full
land-time verification.

Judge item fulfillment from the implementation evidence map and the requirement's
acceptance signal. Task progress is bookkeeping integrity evidence only. SPEC-GUARD
MUST NOT downgrade an item from `IMPLEMENTED` to `PARTIAL`, `UNVERIFIED`, or
`MISSING` solely because `tasks.md` marks the related task pending, when source and executable test evidence satisfy the requirement and acceptance signal.

Evidence-strength rule: runtime threshold requirements, especially `NFR-*`,
`SC-*`, latency, frame-rate, crash-free-rate, retention, cloud-cost, privacy
telemetry, and cross-device replay thresholds, require measured CI/runtime
evidence. `evidence_kind=assertion_only` or synthetic fixture tests may prove
that a gate API/schema exists, but MUST NOT be judged `IMPLEMENTED` for the
threshold itself. Mark those rows `UNVERIFIED` unless the implementation map
cites measured artifacts (`evidence_kind=measured_runtime` or equivalent CI
artifact / runtime metric output) that satisfy the acceptance signal.

Also judge task-progress integrity from `progress-integrity.json` and
`progress-integrity.md`. If progress integrity is invalid or incomplete, write a
`TASK-PROGRESS` row with status `PARTIAL` and include the mismatch in
`{spec_dir}/fulfillment-gaps.md`.

## Expected Outputs

Write:
- `{spec_dir}/fulfillment-report.md`
- `{spec_dir}/fulfillment-gaps.md` only when actionable gaps exist

Ralph stamps `verified_commit` and `verified_at` after a successful
verify-spec fulfillment refresh. Do not inspect Echelon or harness source code
to discover fulfillment-report provenance format. Do not add or repair provenance frontmatter by hand. Do not search sibling repos under `sources/`
for harness, fulfillment, or verify-spec implementation details; those repos
are not part of the targeted implementation evidence unless they are the
explicit delivery target.

After SPEC-GUARD writes fallback-only fulfillment rows, assemble the final
report with:

```bash
python -m harness assemble-fulfillment-report \
  "{verify_run_dir}/canonical-requirements.json" \
  "{verify_run_dir}/judgment-prepass.json" \
  "{spec_dir}/fulfillment-report.md" \
  "{spec_dir}/fulfillment-report.md" \
  "{verify_run_dir}/state.json"
```

Before returning DONE in full scope, perform row-set integrity validation: every
item ID in `{verify_run_dir}/canonical-requirements.json` must appear exactly
once in `{spec_dir}/fulfillment-report.md`, and the report must not invent extra
item IDs. `TASK-PROGRESS` is the only permitted synthetic report row. If
validation fails, hard stop with BLOCKED and do not summarize the run as
complete. In scoped mode, validate that every `scoped_ids` item appears exactly
once and that no other requirement IDs appear in the scoped output.

Do not render summary counts as a markdown table with status labels in the first column.
Use bullets or prose for summary counts. The first column of any report
table is reserved for real requirement IDs or the permitted `TASK-PROGRESS`
synthetic row.

Return summary and recommended action.
