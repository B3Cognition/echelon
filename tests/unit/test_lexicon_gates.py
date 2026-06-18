"""Unit tests for the C / O / E gate modules and artifact_type detection."""

import pytest

from lexicon.completeness import completeness, placeholder_findings
from lexicon.examples import (
    example_coverage,
    missing_example_findings,
    unsupported_claim_findings,
)
from lexicon.observability import missing_output_findings, observability
from lexicon.parser import artifact_type

# --- shared fixtures -------------------------------------------------------

SPEC_FULL = """ARTIFACT: SPEC
TITLE: Overdue task dashboard

REQ: R1
GIVEN: the user has at least one overdue task
WHEN: the user opens the dashboard
THEN: the dashboard MUST display the overdue list
OUTPUT: a visible overdue list
"""

SPEC_NO_OUTPUT = """ARTIFACT: SPEC
TITLE: Overdue task dashboard

REQ: R1
GIVEN: g
WHEN: w
THEN: the dashboard MUST display the overdue list
"""

SPEC_PLACEHOLDER = """ARTIFACT: SPEC
TITLE: <title>

REQ: R1
GIVEN: g
WHEN: w
THEN: the dashboard MUST display <observable result>
OUTPUT: a visible list
"""

ARTICLE_SUPPORTED = """ARTIFACT: ARTICLE
TITLE: t

CLAIM: C1
Controlled grammar reduces ambiguity.

EVIDENCE: E1
The EARS case study reported reductions across eight problem types.

CLAIM: C2
Term governance prevents drift.

EVIDENCE: E2
SKOS assigns one preferred label per concept.
"""

ARTICLE_UNSUPPORTED = """ARTIFACT: ARTICLE
TITLE: t

CLAIM: C1
Controlled grammar reduces ambiguity.

CLAIM: C2
Term governance prevents drift.

EVIDENCE: E2
SKOS assigns one preferred label per concept.
"""


# --- artifact_type ---------------------------------------------------------

@pytest.mark.unit
def test_artifact_type_reads_header():
    assert artifact_type(SPEC_FULL) == "SPEC"
    assert artifact_type(ARTICLE_SUPPORTED) == "ARTICLE"


@pytest.mark.unit
def test_artifact_type_none_when_unparseable():
    assert artifact_type("not a lexicon document") is None


# --- C: completeness -------------------------------------------------------

@pytest.mark.unit
def test_full_spec_is_complete():
    assert completeness(SPEC_FULL) == 1.0
    assert placeholder_findings(SPEC_FULL) == []


@pytest.mark.unit
def test_leftover_placeholders_are_flagged():
    findings = placeholder_findings(SPEC_PLACEHOLDER)
    spans = sorted(f.span for f in findings)
    assert spans == ["<observable result>", "<title>"]
    assert all(f.code == "incomplete-slot" for f in findings)
    assert completeness(SPEC_PLACEHOLDER) < 1.0


# --- O: observability ------------------------------------------------------

@pytest.mark.unit
def test_req_with_output_is_observable():
    assert observability(SPEC_FULL) == 1.0
    assert missing_output_findings(SPEC_FULL) == []


@pytest.mark.unit
def test_req_without_output_is_flagged():
    findings = missing_output_findings(SPEC_NO_OUTPUT)
    assert len(findings) == 1
    assert findings[0].code == "missing-output"
    assert findings[0].span == "R1"
    assert observability(SPEC_NO_OUTPUT) == 0.0


# --- E: example coverage (articles) ---------------------------------------

@pytest.mark.unit
def test_every_claim_supported_is_full_coverage():
    assert example_coverage(ARTICLE_SUPPORTED) == 1.0
    assert unsupported_claim_findings(ARTICLE_SUPPORTED) == []


@pytest.mark.unit
def test_claim_without_evidence_is_flagged():
    findings = unsupported_claim_findings(ARTICLE_UNSUPPORTED)
    assert len(findings) == 1
    assert findings[0].code == "unsupported-claim"
    assert findings[0].span == "C1"
    assert example_coverage(ARTICLE_UNSUPPORTED) == pytest.approx(0.5)


# --- E: spec/story example coverage (REQ -> AC via EXAMPLE ref) ------------

SPEC_LINKED = """ARTIFACT: SPEC
TITLE: t

REQ: FR-001
GIVEN: g
WHEN: w
THEN: the system MUST act
OUTPUT: a result
EXAMPLE: AC-001

AC: AC-001
GIVEN: g
WHEN: w
THEN: the result is visible
"""

SPEC_UNLINKED = """ARTIFACT: SPEC
TITLE: t

REQ: FR-001
GIVEN: g
WHEN: w
THEN: the system MUST act
OUTPUT: a result

AC: AC-001
GIVEN: g
WHEN: w
THEN: the result is visible
"""

SPEC_DANGLING = SPEC_LINKED.replace("EXAMPLE: AC-001", "EXAMPLE: AC-999")


@pytest.mark.unit
def test_req_with_resolved_example_is_covered():
    assert example_coverage(SPEC_LINKED) == 1.0
    assert missing_example_findings(SPEC_LINKED) == []


@pytest.mark.unit
def test_req_without_example_is_flagged():
    findings = missing_example_findings(SPEC_UNLINKED)
    assert len(findings) == 1
    assert findings[0].code == "missing-example"
    assert findings[0].span == "FR-001"
    assert example_coverage(SPEC_UNLINKED) == 0.0


@pytest.mark.unit
def test_req_with_dangling_example_ref_is_flagged():
    findings = missing_example_findings(SPEC_DANGLING)
    assert any(f.code == "unresolved-example" and "AC-999" in f.message for f in findings)
    assert example_coverage(SPEC_DANGLING) == 0.0


@pytest.mark.unit
def test_article_coverage_unaffected_by_spec_logic():
    # Article CLAIM->EVIDENCE coverage still works; no REQ example findings.
    assert example_coverage(ARTICLE_SUPPORTED) == 1.0
    assert missing_example_findings(ARTICLE_SUPPORTED) == []
