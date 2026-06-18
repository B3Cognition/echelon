"""Unit tests for the Lexicon validity aggregator — Valid_k(A)."""

import pytest

from lexicon.validity import validate

GOOD_SPEC = """ARTIFACT: SPEC
TITLE: Overdue task dashboard

REQ: TASK-07
GIVEN: the user has at least one overdue task
WHEN: the user opens the task dashboard
THEN: the dashboard MUST display the overdue list sorted by due_date ascending
OUTPUT: a visible overdue list
CONSTRAINT: latency <= 500 ms for p95 requests
"""

BANNED_SPEC = GOOD_SPEC.replace("the overdue list", "a robust overdue list")

MISSING_THEN = """ARTIFACT: SPEC
TITLE: Broken

REQ: TASK-01
GIVEN: a precondition
WHEN: a trigger
OUTPUT: an observable result
"""


NO_MODAL_SPEC = GOOD_SPEC.replace(
    "the dashboard MUST display the overdue list",
    "the dashboard displays the overdue list",
)


PLACEHOLDER_SPEC = GOOD_SPEC.replace(
    "a visible overdue list", "<observable result>"
)

NO_OUTPUT_SPEC = """ARTIFACT: SPEC
TITLE: t

REQ: R1
GIVEN: g
WHEN: w
THEN: the dashboard MUST display the overdue list sorted by due_date ascending
"""

GOOD_STORY = """ARTIFACT: STORY
TITLE: Manage profile

REQ: STORY-1
GIVEN: a signed-in account holder
WHEN: the account holder edits their display name
THEN: the system MUST persist the new display name

RULE: R1
IF: the display name is empty
THEN: reject the change

AC: A1
GIVEN: a signed-in account holder
WHEN: the account holder saves a valid display name
THEN: the profile shows the new display name
"""

GOOD_ARTICLE = """ARTIFACT: ARTICLE
TITLE: Why controlled authoring helps

CLAIM: C1
Controlled grammar reduces ambiguity in authored specifications.

EVIDENCE: E1
The EARS case study reported reductions across all eight problem types.
"""

UNSUPPORTED_ARTICLE = """ARTIFACT: ARTICLE
TITLE: t

CLAIM: C1
An unsupported assertion.

CLAIM: C2
Another assertion.

EVIDENCE: E2
Only the second claim is backed.
"""


@pytest.mark.unit
def test_good_spec_is_valid_with_glossary():
    report = validate(GOOD_SPEC, glossary={"due_date"})
    assert report.ok is True
    assert report.parse_pass is True
    assert report.term_resolution == 1.0
    assert report.determinism == 1.0
    assert report.completeness == 1.0
    assert report.observability == 1.0
    assert report.example_coverage == 1.0
    assert report.artifact_type == "SPEC"
    assert report.findings == []


@pytest.mark.unit
def test_placeholder_makes_spec_invalid():
    report = validate(PLACEHOLDER_SPEC, glossary={"due_date"})
    assert report.ok is False
    assert report.completeness < 1.0
    assert any(f.code == "incomplete-slot" for f in report.findings)


@pytest.mark.unit
def test_req_without_output_makes_spec_invalid():
    report = validate(NO_OUTPUT_SPEC, glossary={"due_date"})
    assert report.ok is False
    assert report.observability < 1.0
    assert any(f.code == "missing-output" for f in report.findings)


@pytest.mark.unit
def test_story_req_without_output_is_still_valid():
    # O applies to SPEC only; a STORY REQ legitimately has no OUTPUT line.
    report = validate(GOOD_STORY)
    assert report.ok is True
    assert any(f.code == "missing-output" for f in report.findings) is False


@pytest.mark.unit
def test_clean_article_is_valid():
    report = validate(GOOD_ARTICLE)
    assert report.ok is True
    assert report.artifact_type == "ARTICLE"
    assert report.example_coverage == 1.0


@pytest.mark.unit
def test_article_with_unsupported_claim_is_invalid():
    report = validate(UNSUPPORTED_ARTICLE)
    assert report.ok is False
    assert report.example_coverage < 1.0
    assert any(f.code == "unsupported-claim" for f in report.findings)


@pytest.mark.unit
def test_missing_modal_makes_spec_invalid():
    report = validate(NO_MODAL_SPEC, glossary={"due_date"})
    assert report.ok is False
    assert report.determinism < 1.0
    assert any(f.code == "modal" for f in report.findings)


@pytest.mark.unit
def test_banned_word_makes_spec_invalid():
    report = validate(BANNED_SPEC, glossary={"due_date"})
    assert report.ok is False
    assert any(f.code == "banned-word" and f.span == "robust" for f in report.findings)


@pytest.mark.unit
def test_unresolved_term_makes_spec_invalid():
    report = validate(GOOD_SPEC, glossary=set())  # due_date not glossed
    assert report.ok is False
    assert report.term_resolution < 1.0
    assert any(f.code == "unresolved-term" and f.span == "due_date" for f in report.findings)


@pytest.mark.unit
def test_parse_failure_makes_spec_invalid_and_reports_parse_error():
    report = validate(MISSING_THEN, glossary=set())
    assert report.ok is False
    assert report.parse_pass is False
    assert any(f.code == "parse-error" for f in report.findings)
