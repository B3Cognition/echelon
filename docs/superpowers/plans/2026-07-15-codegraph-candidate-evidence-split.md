# CodeGraph Candidate Evidence Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement EGR-141 by splitting CodeGraph structural candidates from verified implementation/test evidence across verify-spec artifacts.

**Architecture:** CodeGraph evidence map becomes schema v2 and emits only candidate structural evidence. IMPLEMENTATION-MAPPER writes a v2 implementation map with verified evidence columns, and Python judgment prepass mechanically classifies only verified evidence. Fulfillment ledger verifier version is bumped so old v1 semantics are not reused.

**Tech Stack:** Python harness, Markdown prompt contracts, pytest.

## Global Constraints

- This is a breaking change for verify-spec run artifacts; do not preserve old v1 implementation-map compatibility.
- CodeGraph candidates are bounded leads and audit context, not fulfillment proof.
- Candidate-empty rows must still be eligible for manual source/test inspection.
- Runtime threshold rows must still require measured runtime evidence.
- Use TDD: write failing tests before implementation code.

---

### Task 1: CodeGraph Evidence Map v2

**Files:**
- Modify: `src/harness/codegraph_evidence_mapper.py`
- Modify: `src/harness/__main__.py`
- Test: `tests/unit/test_codegraph_evidence_mapper.py`

**Interfaces:**
- Consumes: `write_codegraph_evidence_map(...)`
- Produces: `codegraph-evidence-map.json` with `schema_version: 2`, `codegraph_candidates`, `candidate_summary`, `candidate_confidence`, and `manual_review_required`.

- [x] **Step 1: Add failing mapper schema test**

Add assertions to `test_codegraph_evidence_map_prefers_structural_evidence`:

```python
assert payload["schema_version"] == 2
assert "codegraph_candidates" in by_id["FR-004"]
assert "implementation_evidence" not in by_id["FR-004"]
assert "test_evidence" not in by_id["FR-004"]
assert by_id["FR-004"]["candidate_summary"]["source_candidate_count"] >= 1
assert by_id["FR-004"]["candidate_summary"]["test_candidate_count"] >= 1
```

- [x] **Step 2: Run schema test and verify it fails**

Run: `python -m pytest tests/unit/test_codegraph_evidence_mapper.py::test_codegraph_evidence_map_prefers_structural_evidence -q`

Expected: FAIL because current payload is schema v1 and still emits `implementation_evidence` / `test_evidence`.

- [x] **Step 3: Implement v2 candidates**

In `src/harness/codegraph_evidence_mapper.py`, replace per-row output fields:

```python
"codegraph_candidates": candidates,
"candidate_summary": _candidate_summary(candidates),
"candidate_confidence": confidence,
"manual_review_required": confidence in {"low", "none", "ambiguous"},
```

Each candidate should include:

```python
{
    "symbol": symbol.symbol,
    "kind": symbol.kind,
    "file": symbol.file_path,
    "line_start": symbol.line_start,
    "line_end": symbol.line_end,
    "symbol_role": "test" if symbol.is_test else "source",
    "match_reasons": reasons,
    "candidate_strength": _candidate_strength(reasons),
}
```

- [x] **Step 4: Update Markdown renderer**

Render v2 columns:

```markdown
| ID | Candidate Confidence | Manual Review | Source Candidates | Test Candidates | Candidate Reasons | Notes |
```

- [x] **Step 5: Update degraded skip artifact**

In `src/harness/__main__.py`, make skipped map payload use `schema_version: 2` and include `counts` with the full confidence key set.

- [x] **Step 6: Run mapper tests**

Run: `python -m pytest tests/unit/test_codegraph_evidence_mapper.py -q`

Expected: PASS.

### Task 2: Judgment Prepass v2 Parser

**Files:**
- Modify: `src/harness/judgment_prepass.py`
- Test: `tests/unit/test_judgment_prepass.py`

**Interfaces:**
- Consumes: `implementation-map.md` v2 table.
- Produces: unchanged `judgment-prepass.json`, but classification uses only verified evidence cells.

- [x] **Step 1: Add failing old-schema rejection test**

Add a test that writes the old 9-column table and calls `write_judgment_prepass(...)`.

```python
try:
    write_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)
except ValueError as exc:
    assert "expected schema_version: 2" in str(exc)
else:
    raise AssertionError("old implementation-map schema was accepted")
```

- [x] **Step 2: Add failing v2 mechanical/manual tests**

Add v2 implementation-map rows:

```markdown
schema_version: 2

| ID | Verified Implementation Evidence | Verified Test Evidence | CodeGraph Candidates | Candidate Disposition | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-001 | src/a.py:start | tests/test_a.py::test_start |  | none | source_and_test | strong | false | high | manual evidence found |
| FR-002 |  |  | src/generic.py::Registry | candidate_only | source_and_test | strong | false | high | candidate not verified |
```

Expected: FR-001 mechanical `IMPLEMENTED`; FR-002 fallback.

- [x] **Step 3: Run new prepass tests and verify they fail**

Run: `python -m pytest tests/unit/test_judgment_prepass.py -q`

Expected: FAIL before parser implementation.

- [x] **Step 4: Implement v2 parser**

Update `_ImplementationRow` fields to:

```python
verified_implementation_evidence: str
verified_test_evidence: str
codegraph_candidates: str
candidate_disposition: str
evidence_kind: str
evidence_strength: str
runtime_threshold: bool
confidence: str
notes: str
```

Require `schema_version: 2` and the 10-column v2 header.

- [x] **Step 5: Update classification rules**

Use only `verified_implementation_evidence` and `verified_test_evidence` for `IMPLEMENTED` and `MISSING`. Candidate-only rows must fall back unless verified evidence independently satisfies the row.

- [x] **Step 6: Run prepass tests**

Run: `python -m pytest tests/unit/test_judgment_prepass.py -q`

Expected: PASS.

### Task 3: Prompt Contracts v2

**Files:**
- Modify: `extension/workflow/phases/verify-spec-4-map.md`
- Modify: `extension/agents/build/implementation-mapper.md`
- Modify: `extension/workflow/phases/verify-spec-5-judge.md`
- Modify: `extension/agents/build/spec-guard.md`
- Modify: `tests/unit/test_verify_spec_codegraph_prompt.py`
- Modify: `tests/kernel/test_prompt_references.py`

**Interfaces:**
- Produces: prompt contracts requiring v2 candidate-vs-verified evidence split.

- [x] **Step 1: Add failing prompt tests**

Add assertions that Stage 4 and IMPLEMENTATION-MAPPER mention:

```text
Verified Implementation Evidence
Verified Test Evidence
CodeGraph Candidates
Candidate Disposition
candidate-empty rows
```

Also assert the old exact 9-column schema text is absent.

- [x] **Step 2: Run prompt tests and verify they fail**

Run: `python -m pytest tests/unit/test_verify_spec_codegraph_prompt.py tests/kernel/test_prompt_references.py -q`

Expected: FAIL until prompts are updated.

- [x] **Step 3: Update Stage 4 and IMPLEMENTATION-MAPPER**

Replace the old schema table with the v2 10-column schema and add rules that CodeGraph candidates are not verified evidence.

- [x] **Step 4: Update Stage 5 and SPEC-GUARD**

Add wording that SPEC-GUARD judges from verified implementation/test evidence and measured runtime artifacts; CodeGraph candidates are context only.

- [x] **Step 5: Run prompt tests**

Run: `python -m pytest tests/unit/test_verify_spec_codegraph_prompt.py tests/kernel/test_prompt_references.py -q`

Expected: PASS.

### Task 4: Fulfillment Runner Version And Direct Refresh

**Files:**
- Modify: `src/harness/fulfillment_runner.py`
- Test: `tests/unit/test_fulfillment_runner.py`
- Test: `tests/unit/test_verified_fulfillment_ledger.py`

**Interfaces:**
- Produces: new verifier version string and direct refresh behavior with v2 implementation maps.

- [x] **Step 1: Add failing verifier-version test**

Assert `FULFILLMENT_VERIFIER_VERSION == "verified-ledger-v2-codegraph-candidates"`.

- [x] **Step 2: Update direct refresh fixture maps to v2**

Replace old implementation-map tables in fulfillment runner tests with v2 schema.

- [x] **Step 3: Run focused fulfillment tests and verify failure**

Run: `python -m pytest tests/unit/test_fulfillment_runner.py tests/unit/test_verified_fulfillment_ledger.py -q`

Expected: FAIL before version and fixture updates are complete.

- [x] **Step 4: Bump verifier version**

Set:

```python
FULFILLMENT_VERIFIER_VERSION = "verified-ledger-v2-codegraph-candidates"
```

- [x] **Step 5: Run fulfillment tests**

Run: `python -m pytest tests/unit/test_fulfillment_runner.py tests/unit/test_verified_fulfillment_ledger.py -q`

Expected: PASS.

### Task 5: Documentation And Final Verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`

**Interfaces:**
- Produces: EGR-141 completion evidence.

- [x] **Step 1: Add changelog entry**

Under `[Unreleased]`, add an EGR-141 entry naming schema v2, candidate evidence split, and verifier version bump.

- [x] **Step 2: Mark EGR-141 fixed**

Update EGR-141 row with implementation evidence and regression tests.

- [x] **Step 3: Run focused verification**

Run:

```bash
python -m pytest \
  tests/unit/test_codegraph_evidence_mapper.py \
  tests/unit/test_judgment_prepass.py \
  tests/unit/test_verify_spec_codegraph_prompt.py \
  tests/kernel/test_prompt_references.py \
  tests/unit/test_fulfillment_runner.py \
  tests/unit/test_verified_fulfillment_ledger.py \
  -q
```

Expected: PASS.

- [x] **Step 4: Commit**

Run:

```bash
git add CHANGELOG.md docs/findings/echelon-grounded-review-register.md src/harness/codegraph_evidence_mapper.py src/harness/__main__.py src/harness/judgment_prepass.py src/harness/fulfillment_runner.py extension/workflow/phases/verify-spec-4-map.md extension/workflow/phases/verify-spec-5-judge.md extension/agents/build/implementation-mapper.md extension/agents/build/spec-guard.md tests/unit/test_codegraph_evidence_mapper.py tests/unit/test_judgment_prepass.py tests/unit/test_verify_spec_codegraph_prompt.py tests/kernel/test_prompt_references.py tests/unit/test_fulfillment_runner.py tests/unit/test_verified_fulfillment_ledger.py
git commit -m "fix: split CodeGraph candidates from verified evidence"
```
