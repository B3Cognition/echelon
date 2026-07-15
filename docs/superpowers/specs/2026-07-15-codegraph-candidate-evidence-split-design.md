# EGR-141 CodeGraph Candidate Evidence Split Design

## Context

Verify-spec currently uses CodeGraph structural output to seed
`codegraph-evidence-map.json`, then asks IMPLEMENTATION-MAPPER to produce
`implementation-map.md` for Stage 5 judgment. The current CodeGraph evidence map
uses fields named `implementation_evidence` and `test_evidence` even when the
entries are only structural candidates from symbol names, requirement ID
matches, call edges, or term overlap.

Live `906-cli-output-styling` verification exposed the problem: nearly every
row cited the same generic registry symbols such as
`BuiltinRegistrySource::descriptors/version` and
`CatalogRegistrySource::constructor` as implementation evidence. Those symbols
were term-match artifacts, not CLI styling implementation. The model then had
to choose between trusting weak CodeGraph evidence or replacing it during
manual inspection, which risks erasing the deterministic audit trail.

EGR-141 tracks the deeper fix: CodeGraph output should narrow and explain
candidate search paths, but fulfillment proof should come only from verified
source, verified tests, or measured runtime artifacts.

There are no in-progress verification runs that require compatibility with the
old schema. This design intentionally uses a breaking v2 cutover for verify-spec
run artifacts.

## Goals

- Separate structural CodeGraph candidates from verified implementation and
  test evidence.
- Preserve CodeGraph as a bounded search aid and audit trail.
- Ensure absence of CodeGraph candidates does not imply missing implementation.
- Prevent Python prepass from mechanically accepting candidate-only evidence.
- Keep manual fallback inspection available when CodeGraph finds no candidates
  or degrades.
- Make the new schema robust through parser validation, prompt contracts, and
  regression tests.
- Invalidate old verified-ledger reuse across the evidence semantics change.

## Non-Goals

- Do not replace IMPLEMENTATION-MAPPER with a fully Python-owned source
  verifier.
- Do not remove CodeGraph from verify-spec.
- Do not make term matching a fulfillment oracle.
- Do not preserve compatibility with old in-flight verify-spec run artifacts.
- Do not require CodeGraph candidates for a row to be judged implemented.

## Recommended Approach

Use a breaking schema v2 cutover across the CodeGraph evidence map,
implementation map, prepass parser, and verify-spec prompt contracts.

CodeGraph v2 emits candidate structural evidence only. IMPLEMENTATION-MAPPER
reads those candidates first, then performs bounded source/test inspection to
fill verified evidence cells. Stage 5 prepass mechanically classifies rows only
from verified evidence cells and measured runtime semantics, never from
candidate cells alone.

This is preferable to a compatibility projection because the current 9-column
schema is itself part of the problem: it compresses candidate and verified
concepts into columns named as if they are evidence. Keeping that table would
retain the same reasoning trap.

## Current Surfaces Affected

Research found these concrete affected surfaces:

- `src/harness/codegraph_evidence_mapper.py`: emits current schema v1
  `implementation_evidence` and `test_evidence`.
- `extension/workflow/phases/verify-spec-4-map.md`: defines Stage 4 command and
  implementation-map schema.
- `extension/agents/build/implementation-mapper.md`: instructs the agent how to
  consume CodeGraph output and write `implementation-map.md`.
- `extension/workflow/phases/verify-spec-5-judge.md`: describes Stage 5
  prepass and SPEC-GUARD judgment inputs.
- `extension/agents/build/spec-guard.md`: defines fulfillment evidence
  semantics.
- `src/harness/judgment_prepass.py`: parses `implementation-map.md` and
  mechanically classifies rows.
- `src/harness/fulfillment_runner.py`: can assemble fulfillment directly from
  deterministic artifacts and writes verified-ledger metadata.
- `src/harness/verified_fulfillment_ledger.py`: reuses verified rows by
  verifier version and evidence fingerprints.
- Tests under `tests/unit/test_codegraph_evidence_mapper.py`,
  `tests/unit/test_judgment_prepass.py`,
  `tests/unit/test_verify_spec_codegraph_prompt.py`,
  `tests/kernel/test_prompt_references.py`, and selected
  `tests/unit/test_fulfillment_runner.py`.

## Artifact Model

### `codegraph-evidence-map.json` v2

The map remains Python-owned and deterministic. It should set:

```json
{
  "schema_version": 2,
  "summary": {
    "total_requirements": 0,
    "counts": {
      "high": 0,
      "medium": 0,
      "low": 0,
      "none": 0,
      "ambiguous": 0
    },
    "fallback_requirement_ids": []
  },
  "requirements": []
}
```

Each requirement row should replace `implementation_evidence` and
`test_evidence` with candidate-only data:

```json
{
  "id": "FR-001",
  "category": "functional",
  "source": "spec.md#requirements",
  "requirement": "CLI output uses the configured style.",
  "acceptance_signal": "Styled CLI output is asserted by tests.",
  "task_ids": ["T-001"],
  "codegraph_candidates": [
    {
      "symbol": "CliStyleRenderer::render",
      "kind": "function",
      "file": "src/cli/style.ts",
      "line_start": 12,
      "line_end": 44,
      "symbol_role": "source",
      "match_reasons": ["direct_requirement_id_match"],
      "candidate_strength": "strong"
    }
  ],
  "candidate_summary": {
    "source_candidate_count": 1,
    "test_candidate_count": 0,
    "term_match_only": false,
    "has_requirement_anchor": true,
    "has_coverage_anchor": false,
    "has_call_graph_anchor": false
  },
  "candidate_confidence": "medium",
  "manual_review_required": true,
  "runtime_threshold": false,
  "notes": "CodeGraph found structural candidates; manual inspection must verify behavioral fit."
}
```

Candidate reason vocabulary:

- `direct_requirement_id_match`
- `coverage_map_path_match`
- `call_graph_from_test:<test-symbol>`
- `term_match:<tokens>`

Candidate strength vocabulary:

- `strong`: direct requirement ID or coverage-map path evidence.
- `medium`: call graph lifted from a requirement-anchored test.
- `weak`: term-match-only or generic source/test symbol match.

Term-match-only candidates must remain `weak`, must keep
`manual_review_required=true`, and must stay in `fallback_requirement_ids`.

### `codegraph-evidence-map.md` v2

The Markdown view should mirror candidate semantics. It should not have columns
named `Implementation Evidence` or `Test Evidence`. A concise v2 table can use:

```markdown
| ID | Candidate Confidence | Manual Review | Source Candidates | Test Candidates | Candidate Reasons | Notes |
```

This artifact is for humans and agents to orient. The JSON remains the
machine-owned source of truth.

### `implementation-map.md` v2

IMPLEMENTATION-MAPPER writes a breaking v2 table:

```markdown
# Implementation Map

schema_version: 2

| ID | Verified Implementation Evidence | Verified Test Evidence | CodeGraph Candidates | Candidate Disposition | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-001 | src/cli/style.ts:renderTheme | tests/style.test.ts::testTheme | src/cli/style.ts::CliStyleRenderer::render | accepted | source_and_test | strong | false | high | Candidate verified by source/test inspection. |
```

The verified columns are the only columns that count as fulfillment proof.
`CodeGraph Candidates` is an audit/context column. It should preserve relevant
candidate symbols even when they are rejected.

Candidate disposition vocabulary:

- `accepted`: at least one candidate was behaviorally verified and copied into
  a verified evidence cell.
- `contradicted`: a candidate looked relevant but direct source/test inspection
  shows it implements or tests different behavior.
- `unrelated`: candidates are generic term matches or irrelevant symbols.
- `candidate_only`: candidates remain plausible leads but were not verified.
- `none`: CodeGraph produced no candidates for the row.

`Candidate Disposition=none` means only that CodeGraph found no structural
candidate. It does not mean the requirement is missing.

Evidence kind vocabulary can remain the current IMPLEMENTATION-MAPPER contract:

- `source_and_test`
- `source_only`
- `test_only`
- `measured_runtime`
- `assertion_only`
- `missing`
- `meta`

Evidence strength vocabulary remains:

- `strong`
- `medium`
- `weak`
- `none`

## Manual Fallback Semantics

The evidence hierarchy is:

1. CodeGraph candidates are preferred starting points.
2. Absence of CodeGraph candidates is not absence of implementation.
3. Manual source/test inspection is required for fallback rows.

For rows with candidates, IMPLEMENTATION-MAPPER must inspect the cited files and
symbols first, then accept, contradict, or reject them.

For rows with `codegraph_candidates=[]`, IMPLEMENTATION-MAPPER must not stop at
"no CodeGraph evidence." It must perform bounded manual inspection using the
requirement ID, acceptance signal, tasks, coverage map, source tree, tests, and
current verify-spec bounds. If manual inspection finds real evidence, it fills
verified source/test columns and sets `Candidate Disposition=none`. If manual
inspection finds nothing, it leaves verified columns blank, sets
`Confidence=none`, and explains the search path in `Notes`.

This preserves the intended behavior:

- if CodeGraph has candidates, use them first
- if CodeGraph has no candidates, use LLM/manual inspection to find evidence
- if CodeGraph is degraded, fall back to manual inspection under bounded
  verify-spec rules

## Harness Behavior

### CodeGraph Mapper

`write_codegraph_evidence_map()` should emit schema v2. It should still:

- parse requirement audit rows
- parse tasks and requirement IDs
- parse CodeGraph symbols and call graph edges
- use coverage-map path hints when available
- classify runtime threshold rows
- calculate fallback IDs

It should stop emitting fields named `implementation_evidence` and
`test_evidence`. All structural results go into `codegraph_candidates`.

Confidence should be renamed or interpreted as candidate confidence:

- `high`: strong candidate set with direct/coverage anchors and source/test
  roles, still not fulfillment proof
- `medium`: plausible structural candidate set, often with call graph support
- `low`: weak/term-match-only or source-only/test-only candidate set
- `none`: no candidates
- `ambiguous`: contradictory or mixed candidate signals

Rows with `candidate_confidence in {"low", "none", "ambiguous"}` remain in
`summary.fallback_requirement_ids`.

Rows with no candidates must use `candidate_confidence="none"` and
`manual_review_required=true`. Candidate absence is a manual-inspection trigger,
not a fulfillment judgment.

### Judgment Prepass

`judgment_prepass.py` should parse only v2 implementation maps. It should reject
old 9-column maps with a direct error such as:

```text
implementation-map.md uses unsupported schema; expected schema_version: 2 with Verified Implementation Evidence columns
```

The parser should map columns to a new internal row model:

- `verified_implementation_evidence`
- `verified_test_evidence`
- `codegraph_candidates`
- `candidate_disposition`
- `evidence_kind`
- `evidence_strength`
- `runtime_threshold`
- `confidence`
- `notes`

Mechanical classification rules:

- `IMPLEMENTED` can use only verified source/test evidence, evidence kind,
  evidence strength, runtime threshold, confidence, and notes.
- `CodeGraph Candidates` can never mechanically prove `IMPLEMENTED`.
- `Candidate Disposition=accepted` is supportive context only; it is not enough
  without verified evidence cells.
- `Candidate Disposition=none` does not block mechanical `IMPLEMENTED` when
  verified evidence is strong and high confidence.
- `candidate_only`, `contradicted`, and `unrelated` should force fallback unless
  verified source/test evidence independently satisfies the row and notes do not
  require judgment.
- Runtime threshold rows keep the existing measured-runtime rule:
  `assertion_only`, source-only, and synthetic fixture evidence cannot become
  mechanically `IMPLEMENTED`.
- Mechanical `MISSING` requires blank verified source/test evidence,
  `Confidence=none`, and no notes indicating unresolved ambiguity.

### Fulfillment Runner And Ledger

`FULFILLMENT_VERIFIER_VERSION` should be bumped, for example:

```python
FULFILLMENT_VERIFIER_VERSION = "verified-ledger-v2-codegraph-candidates"
```

This invalidates old verified-ledger rows whose evidence semantics came from the
v1 implementation map.

Direct no-fallback refresh remains allowed only when:

- latest verify run has required artifacts
- v2 `write_judgment_prepass()` succeeds
- fallback count is zero
- `_prepass_has_only_no_gap_mechanical_rows()` accepts the v2 prepass
- final fulfillment artifact validation passes

Old v1 maps should fail prepass and therefore not silently produce deterministic
reports.

### State

The existing `state.json` stamp `codegraph_evidence_map=ready` remains. Add a
required schema stamp:

```json
{
  "codegraph_evidence_map_schema": 2
}
```

The schema version in the artifact remains the authoritative parser boundary;
the state stamp gives later phases and debugging output an immediate
Python-owned signal.

## Agent And Prompt Contracts

### Stage 4 Phase Contract

`verify-spec-4-map.md` should say:

- run `write-codegraph-evidence-map` before dispatch
- require schema v2 artifacts
- treat `codegraph_candidates` as structural leads
- inspect candidates first when present
- manually inspect fallback rows when candidates are absent
- output only the v2 `implementation-map.md` table
- never write old `Implementation Evidence | Test Evidence | CodeGraph Evidence`
  schema

### IMPLEMENTATION-MAPPER

The agent contract should say:

- Read `codegraph-evidence-map.json` v2 first.
- For rows with candidates, inspect candidate files/symbols first.
- For candidate-empty rows in the fallback queue, perform bounded manual
  source/test inspection.
- Do not put CodeGraph candidates into verified evidence cells unless direct
  source/test inspection confirms behavioral fit.
- Fill `Candidate Disposition` for every row.
- Use `CodeGraph Candidates` to preserve the audit trail, including rejected
  generic symbols when relevant.

### SPEC-GUARD

SPEC-GUARD should judge fulfillment from:

- `Verified Implementation Evidence`
- `Verified Test Evidence`
- measured runtime artifacts
- requirement acceptance signal

It should treat these as context only:

- `CodeGraph Candidates`
- `Candidate Disposition`
- candidate confidence from the CodeGraph map

`candidate_only`, `contradicted`, and `unrelated` are not fulfillment evidence.

## Testing Strategy

### CodeGraph Evidence Mapper Tests

Add or update tests to assert:

- v2 JSON uses `schema_version=2`.
- v2 rows have `codegraph_candidates`, not `implementation_evidence` or
  `test_evidence`.
- term-match-only source/test rows produce weak candidates and remain in
  fallback IDs.
- requirement-anchored test call edges produce source/test candidates but not
  verified evidence.
- candidate-empty rows produce empty candidates and remain eligible for manual
  fallback.
- degraded CodeGraph skip artifacts either use schema v2 or clearly state
  skipped status without v1 evidence fields.

### Judgment Prepass Tests

Add or update tests to assert:

- old 9-column implementation-map schema is rejected.
- v2 rows with verified source/test evidence, strong evidence strength, high
  confidence, and non-runtime-threshold semantics become mechanically
  `IMPLEMENTED`.
- v2 rows with `Candidate Disposition=none` can still become mechanically
  `IMPLEMENTED` when verified manual evidence is strong.
- candidate-only rows do not become mechanically `IMPLEMENTED`.
- contradicted or unrelated candidate rows fall back unless verified evidence
  independently satisfies the row.
- runtime-threshold assertion-only rows remain mechanically `UNVERIFIED`.
- v2 parser errors are clear enough for verify-spec failure output.

### Prompt Contract Tests

Update prompt tests to assert:

- Stage 4 documents v2 candidate-vs-verified split.
- IMPLEMENTATION-MAPPER must inspect candidate-empty fallback rows manually.
- IMPLEMENTATION-MAPPER forbids using candidates as verified evidence without
  source/test inspection.
- SPEC-GUARD treats CodeGraph candidates as context only.
- old 9-column schema wording is absent.

### Fulfillment Runner And Ledger Tests

Add or update tests to assert:

- verifier version bump invalidates reusable old ledger rows.
- direct deterministic refresh works with v2 implementation maps.
- direct deterministic refresh does not accept old v1 implementation maps.
- cached full reports and scoped ledger reuse remain valid only under the new
  verifier version.

## Migration Plan

This is a breaking change for verify-spec run artifacts.

No migration is required for in-progress runs because there are no active
verification runs to preserve. Existing committed fulfillment reports and
verified ledgers remain historical artifacts, but ledger reuse is invalidated by
the verifier version bump.

Operators who inspect old verify run directories may see v1 maps. New harness
commands should reject those maps for current verification instead of attempting
to infer semantics.

## Risks And Mitigations

### Risk: More fallback rows initially

Splitting candidate from verified evidence may reduce mechanical `IMPLEMENTED`
rows until IMPLEMENTATION-MAPPER fills verified evidence reliably.

Mitigation: the Stage 4 prompt must explicitly require manual inspection for
candidate-empty and candidate-only fallback rows. Existing ledger reuse reduces
cost after successful verification under v2.

### Risk: LLM leaves verified cells blank despite finding evidence

Mitigation: prompt tests pin the expected behavior; judgment prepass falls back
instead of mechanically approving ambiguous rows.

### Risk: Direct deterministic refresh becomes less common

Mitigation: direct refresh should remain possible when v2 verified evidence is
complete and strong. The safety improvement is worth the loss of unsafe
mechanical approvals.

### Risk: Candidate disposition vocabulary is misused

Mitigation: parser validation should reject values outside the vocabulary, and
prompt examples should include accepted, unrelated, and none cases.

## Implementation Order

1. Update CodeGraph evidence mapper schema and Markdown renderer to v2.
2. Update Stage 4 and IMPLEMENTATION-MAPPER prompts to consume v2 and write v2
   implementation maps.
3. Update judgment prepass parser and classification rules for v2 maps.
4. Update SPEC-GUARD prompt to treat candidates as context only.
5. Bump fulfillment verifier version and update direct refresh expectations.
6. Update tests across mapper, prepass, prompt contracts, and fulfillment
   runner.
7. Update EGR-141 register row and changelog when implementation is complete.

## Acceptance Criteria

- CodeGraph map v2 never names structural candidates as implementation/test
  evidence.
- Implementation map v2 separates verified evidence from CodeGraph candidates.
- Candidate-empty rows can still be verified through manual source/test
  inspection.
- Python prepass rejects old implementation-map schema.
- Python prepass never mechanically implements candidate-only rows.
- Fulfillment ledger reuse is invalidated by the verifier version bump.
- Prompt tests prevent reintroducing candidate-as-proof language.
- Focused mapper, judgment prepass, prompt-contract, and fulfillment-runner
  tests pass.
