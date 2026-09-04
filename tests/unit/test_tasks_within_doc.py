import pytest
from lexicon.tasks import within_doc_findings


def _doc(test_text="a concrete test runs and asserts the result",
         acc_items=("the run list renders one row per discovered run directory",)):
    items = "\n".join(f"  - [ ] {item}" for item in acc_items)
    return (
        "# Tasks: t\n\n"
        "- [ ] T-001 complexity=standard phase=foundation req=REQ-001 depends=none\n\n"
        "  **Title:** Do the thing\n"
        "  **Description:** Build it.\n"
        f"  **Test:** {test_text}\n"
        "  **Acceptance Criteria:**\n"
        f"{items}\n"
    )


@pytest.mark.unit
def test_banned_word_in_acceptance_flagged():
    f = within_doc_findings(_doc(acc_items=("the system is robust",)), set())
    assert any(x.code == "banned-word" for x in f)


@pytest.mark.unit
def test_compound_acceptance_not_atomic():
    f = within_doc_findings(
        _doc(acc_items=("the list renders and the cost panel updates and an email is sent",)),
        set(),
    )
    assert any(x.code == "task-not-atomic" for x in f)


@pytest.mark.unit
def test_placeholder_flagged():
    f = within_doc_findings(_doc(acc_items=("renders <TBD> rows",)), set())
    assert any(x.code == "incomplete-slot" for x in f)


@pytest.mark.unit
def test_clean_task_has_no_within_doc_findings():
    f = within_doc_findings(
        _doc(acc_items=("the run list renders one row per discovered run directory",)),
        set(),
    )
    assert f == []
