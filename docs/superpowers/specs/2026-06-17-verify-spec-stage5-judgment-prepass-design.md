# Verify-Spec Stage 5 Judgment Pre-Pass Design

## Problem

Stage 4 made scoped fulfillment refresh possible, but not cheap enough. Recent
harness runs still spend large amounts of provider budget in the late
`verify-spec` phases because SPEC-GUARD re-reads broad artifacts and re-judges
too many rows, even when most requirement rows are already mechanically settled
by the canonical inventory and CodeGraph-backed implementation map.

The harness needs a way to reduce token burn in both:

- scoped fulfillment refreshes during active harness loops
- full `verify-spec` runs where most rows are already deterministic

without weakening report integrity, land-time safety, or runtime-threshold
semantics.

## Goals

- Reduce LLM judgment surface area for both full and scoped `verify-spec`.
- Keep canonical row ownership in Python and preserve exact row-set integrity.
- Make cheap judgments deterministic and auditable.
- Bound SPEC-GUARD to unresolved rows only.
- Preserve strict handling of runtime-threshold requirements.

## Non-Goals

- Do not replace SPEC-GUARD entirely.
- Do not promote weak or assertion-only evidence to `IMPLEMENTED`.
- Do not make scoped reports sufficient for land.
- Do not infer `DEVIATED` or `OBSOLETE_SPEC` mechanically in the first slice.

## Recommended Approach

Add a Python-owned judgment pre-pass between `implementation-map.md` and the
SPEC-GUARD dispatch. The pre-pass mechanically classifies rows that are already
decidable from deterministic inputs, and emits a bounded fallback queue for
rows that still require LLM judgment.

The resulting Stage 5 flow becomes:

1. Python reads canonical inventory, requirement audit, implementation map, and
   verify state.
2. Python emits a judgment pre-pass artifact:
   - mechanically judged rows
   - unresolved rows
   - fallback reasons
3. SPEC-GUARD receives only unresolved IDs.
4. Python assembles the final fulfillment report from:
   - mechanical rows
   - SPEC-GUARD rows
5. Python validates exact row-set integrity and writes final artifacts.

This preserves the existing architecture while removing the broad LLM
re-judgment of already-settled rows.

## Artifact Changes

### New Verify Artifacts

Add Python-owned artifacts in `{verify_run_dir}`:

- `judgment-prepass.json`
- `judgment-prepass.md` (optional but recommended for operator inspection)

`judgment-prepass.json` should contain one entry per in-scope requirement ID:

```json
{
  "rows": [
    {
      "id": "FR-001",
      "mechanical": true,
      "proposed_status": "IMPLEMENTED",
      "reason_code": "source_and_test_strong",
      "fallback_reason": null
    }
  ],
  "summary": {
    "mechanical_count": 0,
    "fallback_count": 0,
    "fallback_ids": []
  }
}
```

### No Change to Canonical Ownership

The canonical requirement inventory remains Python-owned. SPEC-GUARD continues
to be forbidden from inventing or removing rows. The pre-pass consumes only the
existing canonical row set.

## Mechanical Judgment Rules

The pre-pass must be conservative. It may classify rows only when the status is
already defensible from deterministic artifacts.

### Mechanically `MISSING`

A row becomes `MISSING` when:

- implementation evidence is blank
- test evidence is blank
- confidence is `none`
- no contradiction flag requires human interpretation

### Mechanically `UNVERIFIED`

A row becomes `UNVERIFIED` when:

- it is a runtime-threshold row, and
- `evidence_kind=assertion_only` or equivalent non-measured evidence, and
- no measured runtime artifact is cited

This preserves the current strict rule for `NFR-*`, `SC-*`, latency, frame
rate, crash-free, retention, cloud-cost, privacy telemetry, and similar rows.

### Mechanically `IMPLEMENTED`

A row may become `IMPLEMENTED` only when all of the following hold:

- not a runtime-threshold row
- deterministic evidence is present
- implementation evidence is concrete
- executable test evidence is present
- evidence strength and confidence meet a configured threshold
- no contradiction flag is present

The first slice should bias hard toward safety:

- allow only `confidence=high`
- require both implementation and test evidence
- exclude rows with notes that indicate partiality, ambiguity, divergence, or
  missing acceptance coverage

### Mechanically Preserved in Scoped Mode

In scoped mode, non-impacted rows are not re-judged. They are preserved from
the last full report exactly as Stage 4 already intends.

## Fallback Queue Rules

Rows fall back to SPEC-GUARD when any of the following is true:

- confidence below the mechanical threshold
- evidence is contradictory
- row may be `PARTIAL`
- row may be `DEVIATED`
- row may be `OBSOLETE_SPEC`
- acceptance signal requires interpretive reasoning
- runtime-threshold row has measured evidence that still needs judgment

The fallback queue is the only row set SPEC-GUARD should judge.

For full runs, fallback IDs may be any canonical rows not mechanically settled.
For scoped runs, fallback IDs must be limited to unresolved `scoped_ids`.

## Full vs Scoped Behavior

### Full Verify

For full `verify-spec`:

- pre-pass runs over the full canonical inventory
- mechanical rows are finalized in Python
- SPEC-GUARD receives only unresolved IDs
- Python assembles the final `fulfillment-report.md`

This makes full runs cheaper when most rows are strongly settled by deterministic
artifacts.

### Scoped Verify

For scoped `verify-spec`:

- pre-pass runs only over `scoped_ids`
- mechanical scoped rows are finalized in Python
- SPEC-GUARD receives only unresolved scoped IDs
- Python assembles the scoped report
- Ralph merges that scoped output over the last full report

This makes scoped refresh materially cheaper instead of merely smaller in row
count.

## Dispatch Contract Changes

### verify-spec-5-judge Phase Contract

Update the phase contract so that SPEC-GUARD receives:

- `judgment-prepass.json`
- `judgment-prepass.md`
- only the unresolved row IDs

The contract should explicitly state:

- Python-owned mechanical judgments are authoritative for those rows
- SPEC-GUARD must judge only the unresolved queue
- SPEC-GUARD must not restate mechanical rows

### SPEC-GUARD Prompt Contract

The SPEC-GUARD prompt should state:

- full mode: judge only `fallback_ids`
- scoped mode: judge only unresolved `scoped_ids`
- do not emit rows for mechanically decided IDs
- do not summarize scoped output as a full replacement report

## Final Report Assembly

Python should own final report assembly in both modes.

### Full Mode

Assemble one final report containing:

- mechanically judged rows
- SPEC-GUARD rows for fallback IDs
- `TASK-PROGRESS` synthetic row when required

### Scoped Mode

Assemble a scoped report for the impacted row set only, then merge it over the
base full report using the existing Stage 4 merge behavior.

## Integrity Validation

Row-set integrity should remain Python-owned.

### Full Mode Validation

- every canonical ID appears exactly once
- no extra requirement IDs appear
- `TASK-PROGRESS` remains the only allowed synthetic row

### Scoped Mode Validation

- every in-scope `scoped_id` appears exactly once in the scoped output
- no out-of-scope requirement IDs appear

Any validation failure remains a hard stop.

## Error Handling

- Missing `judgment-prepass` artifact is a hard phase failure.
- If the fallback queue is empty, SPEC-GUARD dispatch is skipped entirely.
- If SPEC-GUARD returns rows outside the fallback queue, hard stop.
- If scoped mode lacks a base full report, fail as it does today.

## Testing

### Unit Tests

- pre-pass classifies no-evidence rows as `MISSING`
- pre-pass classifies assertion-only threshold rows as `UNVERIFIED`
- pre-pass classifies strong non-threshold rows as `IMPLEMENTED`
- ambiguous and contradictory rows go to fallback

### Assembly Tests

- full report assembly preserves canonical order
- scoped assembly includes only scoped IDs
- merged scoped report preserves unaffected rows

### Integration Tests

- full runs with mostly deterministic rows produce a small fallback queue
- scoped runs with few impacted rows dispatch a very small SPEC-GUARD queue
- empty fallback queue skips SPEC-GUARD entirely
- row-set validation still blocks malformed outputs

### Regression Coverage

Add a regression test modeled after the expensive NavigationalPortal behavior:

- large implementation map
- many mechanically settled rows
- small unresolved subset
- final report assembled without broad LLM re-judgment

## Rollout

Implement Stage 5 in this order:

1. Add Python-owned `judgment-prepass` artifact generation.
2. Add conservative mechanical classification rules.
3. Narrow SPEC-GUARD dispatch to fallback IDs.
4. Add Python-owned final report assembly and row validation.
5. Expand classification rules only after the conservative path proves stable.

This keeps the first slice safe while directly attacking the token-heavy late
judgment stages.
