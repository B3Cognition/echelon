"""Unit tests for the Lexicon banned-word linter."""

import pytest

from lexicon.linter import banned_word_findings

CLEAN_SPEC = """ARTIFACT: SPEC
TITLE: Overdue task dashboard

REQ: TASK-07
GIVEN: the user has at least one overdue task
WHEN: the user opens the task dashboard
THEN: the dashboard MUST display all overdue tasks sorted by due_date ascending
OUTPUT: a visible overdue-task list
CONSTRAINT: latency <= 500 ms for p95 requests
"""

# Same shape, but the THEN line smuggles in two banned words.
BANNED_SPEC = """ARTIFACT: SPEC
TITLE: Overdue task dashboard

REQ: TASK-07
GIVEN: the user has at least one overdue task
WHEN: the user opens the task dashboard
THEN: the dashboard MUST display a robust and fast overdue-task list
"""


@pytest.mark.unit
def test_clean_spec_has_no_banned_words():
    assert banned_word_findings(CLEAN_SPEC) == []


@pytest.mark.unit
def test_banned_words_are_flagged_with_line_and_span():
    findings = banned_word_findings(BANNED_SPEC)
    spans = sorted(f.span for f in findings)
    assert spans == ["fast", "robust"]
    assert all(f.code == "banned-word" for f in findings)
    # Both occur on the THEN line (line 7 of the document).
    assert all(f.line == 7 for f in findings)


@pytest.mark.unit
def test_banned_word_match_is_case_insensitive_and_whole_word():
    # "Robustness" must NOT trip the "robust" rule (whole-word only);
    # "ROBUST" must (case-insensitive).
    text = "ARTIFACT: SPEC\nTITLE: t\n\nCLAIM: C1\nThe ROBUST design improves robustness.\n"
    spans = [f.span for f in banned_word_findings(text)]
    assert spans == ["ROBUST"]
