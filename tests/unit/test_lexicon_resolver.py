"""Unit tests for the Lexicon term resolver — T(A)."""

import pytest

from lexicon.resolver import term_resolution, unresolved_terms

# Uses domain identifiers: authorization_request, Payment_Gateway, due_date
# (all glossed) and card_network (not glossed). ERROR_CODE: is a grammar
# label and must NOT be counted as a content term.
SPEC = """ARTIFACT: SPEC
TITLE: Payments

REQ: PAY-01
GIVEN: a submitted authorization_request
WHEN: the Payment_Gateway responds
THEN: the system MUST record the card_network and due_date
ERROR_CODE: NONE
"""

GLOSSARY = {"authorization_request", "Payment_Gateway", "due_date"}


@pytest.mark.unit
def test_unresolved_terms_lists_only_unglossed_identifiers():
    findings = unresolved_terms(SPEC, GLOSSARY)
    assert [f.span for f in findings] == ["card_network"]
    assert findings[0].code == "unresolved-term"
    assert findings[0].line == 7  # the THEN line


@pytest.mark.unit
def test_grammar_label_is_not_a_content_term():
    # ERROR_CODE: is a label; it must not appear as an unresolved term even
    # though it is snake_case-shaped.
    assert all(f.span != "ERROR_CODE" for f in unresolved_terms(SPEC, set()))


@pytest.mark.unit
def test_term_resolution_is_resolved_over_total():
    # 4 content terms, 3 resolve -> 0.75
    assert term_resolution(SPEC, GLOSSARY) == pytest.approx(0.75)


@pytest.mark.unit
def test_no_content_terms_resolves_vacuously():
    text = "ARTIFACT: SPEC\nTITLE: t\n\nCLAIM: C1\nplain english only here\n"
    assert term_resolution(text, set()) == 1.0
