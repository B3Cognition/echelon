"""Unit tests for the Lexicon determinism gate — D(A), single-modal rule."""

import pytest

from lexicon.determinism import determinism, modal_findings


def _spec(then_line: str) -> str:
    return (
        "ARTIFACT: SPEC\nTITLE: t\n\n"
        "REQ: R1\n"
        "GIVEN: a precondition\n"
        "WHEN: a trigger\n"
        f"THEN: {then_line}\n"
    )


ONE_MODAL = _spec("the dashboard MUST display the list")
NO_MODAL = _spec("the dashboard displays the list")
TWO_MODALS = _spec("the dashboard MUST display and SHALL refresh the list")
MUST_NOT = _spec("the dashboard MUST NOT expose other users data")

# An AC THEN line has no modal by design — it must NOT be flagged.
SPEC_WITH_AC = (
    "ARTIFACT: SPEC\nTITLE: t\n\n"
    "REQ: R1\nGIVEN: g\nWHEN: w\nTHEN: the system MUST act\n\n"
    "AC: A1\nGIVEN: g\nWHEN: w\nTHEN: the result is visible\n"
)


@pytest.mark.unit
def test_single_modal_is_deterministic():
    assert determinism(ONE_MODAL) == 1.0
    assert modal_findings(ONE_MODAL) == []


@pytest.mark.unit
def test_must_not_counts_as_one_modal():
    assert determinism(MUST_NOT) == 1.0
    assert modal_findings(MUST_NOT) == []


@pytest.mark.unit
def test_missing_modal_is_flagged():
    findings = modal_findings(NO_MODAL)
    assert len(findings) == 1
    assert findings[0].code == "modal"
    assert findings[0].line == 7
    assert determinism(NO_MODAL) == 0.0


@pytest.mark.unit
def test_two_modals_are_flagged():
    findings = modal_findings(TWO_MODALS)
    assert len(findings) == 1
    assert findings[0].code == "modal"
    assert determinism(TWO_MODALS) == 0.0


@pytest.mark.unit
def test_ac_then_line_is_not_modal_checked():
    # Only the REQ main clause is normative; the AC observable THEN is exempt.
    assert modal_findings(SPEC_WITH_AC) == []
    assert determinism(SPEC_WITH_AC) == 1.0
