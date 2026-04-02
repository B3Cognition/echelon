# Test Strategy — Spec 015: CA Outcomes Validation
**Agent**: SENTINEL | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Covers**: All 8 REQs and 5 spec-level ACs in spec.md

---

## 1. Testing Approach

Spec 015 is a research validation spec. It produces documents and structured artifacts — not executable code. Accordingly, the tests defined here are **deliverable-quality verification checks**, not unit tests, integration tests, or end-to-end automation suites.

Each REQ delivers one or more artifacts (a table, a search record, a dataset, an experiment design document). A test for this spec checks whether a delivered artifact satisfies each of its Acceptance Criteria. The verdict for each AC is binary: PASS or FAIL. There is no partial credit within a single AC — partial satisfaction is a FAIL on that AC.

This means the test executor's job is to:
1. Locate the artifact produced for a given REQ.
2. For each AC of that REQ, apply the corresponding verification procedure to the artifact.
3. Record PASS or FAIL.
4. Collate into a per-REQ and overall verdict.

No test in this spec requires running any experiment. The NS-003 prototype experiment (REQ-015-006) and the U-CA-004 gate experiment (REQ-015-008) are post-spec engineering and research activities. Verification under this strategy confirms only that the *experiment design documents* are complete, internally consistent, and sufficiently specific for a third party to execute — not that the experiments have been run or that their results are available.

---

## 2. Test Types Used

### 2.1 AC Compliance Check (PASS/FAIL per AC)

Applied to every AC in the spec. The procedure is: read the artifact produced by the REQ, check whether it satisfies the exact wording of the AC, record PASS or FAIL. Where an AC states a precise numeric criterion (e.g., "exactly 17 rows," "citation rate per database," "formula stated," "threshold ≥ 0.80"), the check is deterministic. Where an AC states a qualitative criterion (e.g., "level of specificity such that a third party can execute without requesting clarification"), the check applies a defined rubric: the evaluator simulates being a third party with no prior knowledge of the spec and assesses whether any of the five listed specificity items (metric formula, acceptance threshold, evaluation set construction, test codebase selection, decision rule) would require a clarification question.

### 2.2 Citation Verification

Applied specifically to REQ-015-001 (proof status table), REQ-015-002 (novelty search record), and AC-SPEC-001. Every cited arxiv ID or DOI must correspond to a real, retrievable paper. The citation verification procedure: attempt retrieval of each unique arxiv ID and DOI cited in the delivered artifact. A citation is verified if the paper exists at the cited identifier, the paper title and subject are consistent with the claim it supports, and the cited metric (e.g., "86%+ schema compliance," "93.3% accuracy") appears in the paper. A citation is FAIL if the identifier does not resolve, if the paper subject does not match the claim, or if the cited metric does not appear in the paper. Placeholder arxiv IDs (non-existent or incorrect) are a FAIL on AC-SPEC-001.

Key arxiv IDs requiring verification:
- `arxiv:2510.09355` — NL2GenSym (cited for NS-003-A, 86%+ Generator-Critic compliance)
- `arxiv:2603.17244` — Kumiho (cited for NS-003-B, 93.3% belief revision accuracy)
- `arxiv:2211.17192` — Speculative Decoding (cited for NOVEL-004 structural analogy)
- `arxiv:2309.02427` — CoALA (cited for Goal Stack and Episodic Memory overlays)

### 2.3 Speculation Label Enforcement

Applied to AC-001-003, AC-007-005, AC-SPEC-003, and every location where NOVEL-004 40-70% token reduction is mentioned. The check: search the artifact text for the exact phrase "SPECULATION: no empirical grounding" or equivalent. Verify the label is present in all required locations. Verify the label has not been softened to "probable," "likely," "supported," or equivalent hedged language. This is a string-presence check with a negation component (check that softening language is absent). FAIL if either component fails.

### 2.4 Gate-Condition Enforcement

Applied to AC-001-004, AC-SPEC-002, and every mention of the five CA overlays (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory). The check: verify that each CA overlay is stated as GATE-CONDITIONED on U-CA-004 in every artifact location where it is mentioned. Verify that no overlay is stated as "proven," "supported," "ready for implementation," or "validated" before U-CA-004 resolves positively. This enforcement must be applied not just to the proof-status-table.md rows but to any summary or recommendation section in any artifact produced under spec 015.

---

## 3. Special Considerations

### REQ-015-002: Search Record Reproducibility

The search record artifact (AC-002-001 through AC-002-005) must satisfy a reproducibility test that goes beyond AC compliance. The test: a third party must be able to re-execute the identical search using only the information in the search record, within 30 days of the stated execution date, and obtain a result that can be compared with the original to detect any new matching papers that have appeared in the interval. This means the record must state the exact query string (verbatim, not paraphrased), all databases queried with their access method, and the date of execution to the day. An AC-002-001 PASS is necessary but not sufficient for this reproducibility test — the evaluator must additionally confirm that the query string as recorded is mechanically re-executable, not merely described in prose.

### REQ-015-006 and REQ-015-008: Third-Party Executability Test

Both experiment design documents carry the requirement that a third party with access to spec 014 and spec 015 can execute the experiment "without requesting clarification." The verification of this criterion is applied as a structured five-item checklist for each document:
1. Is the metric formula stated in full, not referred to by name alone?
2. Is the acceptance threshold a specific number, not a range or qualitative descriptor?
3. Is the evaluation set construction method stated (how to build the test set, not just its size)?
4. Is the test codebase selection criterion stated, and is the codebase either named or fully specified by selection rules?
5. Is the decision rule stated in advance with specific thresholds for each of the three possible outcomes?

PASS requires all five items to be verifiable from the document text without reference to any external artifact not listed as a dependency. This check applies AC-SPEC-005 operationally.

### REQ-015-007: Symbolic Break-Even Dependency

REQ-015-007 has a soft dependency on REQ-015-003 (token baseline) for break-even formula instantiation. If REQ-015-003 is not yet complete at the time REQ-015-007 is evaluated, the test procedure accepts the symbolic form of the break-even formula as a PASS on AC-007-004, provided the symbolic form is correctly specified and marked as pending. The evaluator must verify that (a) the symbolic formula matches the stated formula in AC-007-004, and (b) the pending notation explicitly states that instantiation awaits REQ-015-003 completion. A missing symbolic form or an unjustified substitution of an assumed token count is a FAIL.

---

## 4. What Is NOT Tested

The following activities are explicitly out of scope for this test strategy:

- **Running the NS-003 prototype experiment** — REQ-015-006 delivers the design document; this strategy verifies the design document only.
- **Running the U-CA-004 gate experiment** — REQ-015-008 delivers the specification; this strategy verifies the specification only.
- **Actual token measurement** — REQ-015-003 deliverable is a baseline dataset; this strategy verifies the dataset's completeness and structure, not the token measurement methodology itself.
- **Independent annotation of scope violations** — REQ-015-004 deliverable is an annotation artifact; this strategy verifies that the artifact has the required content fields, not that the annotations are substantively correct.
- **Semantic correctness of contradiction detection** — REQ-015-005 deliverable is a scan artifact; this strategy verifies structural completeness (required fields present, detection method stated, sample review included), not whether the detection method is the best available method.
- **Upgrading or downgrading any proof verdict** — this strategy does not re-adjudicate proof categories. It verifies that the delivered verdicts comply with the ACs, not that the verdicts are independently correct.

---

## 5. Test Execution Order

Tests can be applied in any order within a single REQ, but REQ-level evaluation should follow the dependency structure of the spec:

1. REQ-015-001 and REQ-015-002 first — they are the foundational deliverables; all other REQs reference their verdicts.
2. REQ-015-003, REQ-015-004, REQ-015-005 in parallel — baselines, share the same artifact corpus.
3. REQ-015-006 and REQ-015-008 in parallel — experiment designs, independent.
4. REQ-015-007 after REQ-015-003 has been evaluated — to determine whether symbolic break-even is appropriate or whether instantiated values are available.
5. Spec-level ACs (AC-SPEC-001 through AC-SPEC-005) last — they span all artifacts and require all REQ-level artifacts to be present.
