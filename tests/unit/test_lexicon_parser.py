"""Unit tests for the Lexicon grammar parser — P(A), the parse-pass hard gate."""

import pytest

from lexicon.parser import parse_pass

# The canonical "good" spec from the Deterministic Grammar design doc (p.14),
# wrapped in the ARTIFACT/TITLE header from the spec template (p.12).
GOOD_SPEC = """ARTIFACT: SPEC
TITLE: Overdue task dashboard

REQ: TASK-07
GIVEN: the user has at least one overdue task
WHEN: the user opens the task dashboard
THEN: the dashboard MUST display all overdue tasks sorted by due_date ascending
OUTPUT: a visible overdue-task list
CONSTRAINT: latency <= 500 ms for p95 requests
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

LIMIT: L1
Grammar control does not guarantee semantic correctness.
"""

SPEC_WITH_TBR = """ARTIFACT: SPEC
TITLE: Payments

TBR: PAY-RATE
OWNER: payments-team
RESOLVE_BY: 2026-09-01
IMPACT: blocks throughput sizing
"""

# Missing the mandatory THEN line in the REQ block.
SPEC_MISSING_THEN = """ARTIFACT: SPEC
TITLE: Broken

REQ: TASK-01
GIVEN: a precondition
WHEN: a trigger
OUTPUT: an observable result
"""

SPEC_NO_HEADER = """REQ: TASK-01
GIVEN: a precondition
WHEN: a trigger
THEN: the system MUST act
"""

FREE_PROSE = "The system should let users quickly and easily manage overdue tasks.\n"


@pytest.mark.unit
def test_valid_spec_parses():
    assert parse_pass(GOOD_SPEC) is True


@pytest.mark.unit
def test_valid_story_parses():
    assert parse_pass(GOOD_STORY) is True


@pytest.mark.unit
def test_valid_article_parses():
    assert parse_pass(GOOD_ARTICLE) is True


@pytest.mark.unit
def test_spec_with_tbr_placeholder_parses():
    assert parse_pass(SPEC_WITH_TBR) is True


@pytest.mark.unit
def test_req_without_then_fails():
    assert parse_pass(SPEC_MISSING_THEN) is False


@pytest.mark.unit
def test_spec_without_header_fails():
    assert parse_pass(SPEC_NO_HEADER) is False


@pytest.mark.unit
def test_free_prose_fails():
    assert parse_pass(FREE_PROSE) is False


@pytest.mark.unit
def test_trailing_newline_not_required():
    assert parse_pass(GOOD_SPEC.rstrip("\n")) is True
