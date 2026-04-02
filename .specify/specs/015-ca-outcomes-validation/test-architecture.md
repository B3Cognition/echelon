# Test Architecture — Spec 015: CA Outcomes Validation
**Agent**: SENTINEL | **Run**: squad-1775154996 | **Date**: 2026-04-02

---

## 1. Test Type Definitions

| Code | Test Type | Description |
|------|-----------|-------------|
| ACC | AC Compliance Check | Verify the artifact satisfies the exact wording of the AC. Binary PASS/FAIL. |
| CIT | Citation Verification | Verify each cited arxiv ID or DOI resolves to a real paper whose content supports the cited claim. |
| SLB | Speculation Label Enforcement | Verify "SPECULATION: no empirical grounding" is present where required; verify no softening language present. |
| GCE | Gate-Condition Enforcement | Verify CA overlay claims carry "GATE-CONDITIONED on U-CA-004" in all required locations; verify no overlay stated as proven/ready. |
| TPE | Third-Party Executability Check | Apply the 5-item structured checklist (formula stated, threshold numeric, evaluation set construction method stated, codebase selection stated, decision rule pre-registered) to experiment design documents. |
| REP | Reproducibility Check | Verify a search record is complete enough for independent re-execution within 30 days (query verbatim, databases named, date to the day, result counts). |

---

## 2. Test Type to REQ Mapping

| REQ | Primary Test Types | Key Notes |
|-----|--------------------|-----------|
| REQ-015-001 | ACC, CIT, SLB, GCE | All five ACs require ACC; AC-001-003 adds SLB; AC-001-004 adds GCE; AC-001-005 adds CIT on two arxiv IDs |
| REQ-015-002 | ACC, CIT, REP | ACC for AC-002-001 through AC-002-005; REP for overall reproducibility of the search record; CIT to verify the search query is coherent with the cited combination |
| REQ-015-003 | ACC | Purely structural: ACC on each of the five AC fields (logging completeness, run count, summary statistics, machine-readable format, method statement) |
| REQ-015-004 | ACC | ACC on five ACs covering selection criteria, annotation granularity, annotator count, output fields, and BORDERLINE exclusion |
| REQ-015-005 | ACC | ACC on five ACs covering corpus coverage, detection method statement, output fields, 5-sample manual review, and bound declaration |
| REQ-015-006 | ACC, CIT, TPE | ACC on all seven ACs; TPE for the "third party can execute" criterion (AC-006-007); CIT on baseline papers cited in rationale sections |
| REQ-015-007 | ACC, SLB | ACC on six ACs; SLB to verify SPECULATION label present on 40-70% claim (AC-007-005) regardless of calibration outcome |
| REQ-015-008 | ACC, GCE, TPE | ACC on all seven ACs; GCE to verify all five CA overlays remain gate-conditioned in the specification; TPE for "third party can execute" criterion (AC-008-007 via AC-SPEC-005) |

---

## 3. Spec-Level AC to Test Type Mapping

| Spec-Level AC | Test Types | Scope |
|---------------|------------|-------|
| AC-SPEC-001 | ACC, CIT | All artifacts: no verdict uses "believed," "expected," or "likely" without citation; all cited arxiv IDs and DOIs resolve to real papers |
| AC-SPEC-002 | GCE | All artifacts: CA overlays gate-conditioned throughout; no overlay stated as proven/ready before U-CA-004 positive |
| AC-SPEC-003 | SLB | Proof status table (REQ-015-001) and calibration artifact (REQ-015-007): SPECULATION label present, not softened |
| AC-SPEC-004 | REP | Novelty search record (REQ-015-002): complete enough for third-party re-execution |
| AC-SPEC-005 | TPE | Experiment design documents (REQ-015-006, REQ-015-008): all five specificity items verifiable from document text |

---

## 4. Test Coverage Summary

| Test Type | REQs Covered | Spec-Level ACs Covered |
|-----------|--------------|------------------------|
| ACC | REQ-015-001 through REQ-015-008 (all 8) | AC-SPEC-001 |
| CIT | REQ-015-001, REQ-015-002, REQ-015-006 | AC-SPEC-001 |
| SLB | REQ-015-001, REQ-015-007 | AC-SPEC-003 |
| GCE | REQ-015-001, REQ-015-008 | AC-SPEC-002 |
| TPE | REQ-015-006, REQ-015-008 | AC-SPEC-005 |
| REP | REQ-015-002 | AC-SPEC-004 |

Every REQ is covered by at least ACC. The most test-type-intensive deliverable is REQ-015-001 (four test types: ACC, CIT, SLB, GCE), which is appropriate given that it is the primary deliverable and carries the most consequential proof verdicts.

---

## 5. Failure Severity Classification

Where a test fails, the severity determines whether the deliverable can proceed with a documented exception or must be remediated before the spec is considered complete.

| Severity | Definition | Examples |
|----------|------------|---------|
| BLOCKING | The deliverable cannot be accepted. The AC is a hard correctness requirement. | Row count ≠ 17 (AC-001-001); SPECULATION label absent (AC-001-003); arxiv ID does not resolve (AC-SPEC-001); CA overlay stated as proven before U-CA-004 (AC-SPEC-002) |
| MAJOR | The deliverable is materially incomplete. Remediation required before spec closure. | Missing required fields in a table row (AC-001-002); search record not reproducible (AC-SPEC-004); metric formula absent from experiment design (AC-SPEC-005) |
| MINOR | The deliverable satisfies the AC's intent but has a presentation gap. Remediation recommended, not blocking. | Single annotator without explicit limitation statement (AC-004-003); token measurement method ambiguity (AC-003-005) |

BLOCKING failures escalate to CARTOGRAPHER for spec amendment. MAJOR failures escalate to the producing agent for artifact remediation. MINOR failures are logged but do not block spec closure.
