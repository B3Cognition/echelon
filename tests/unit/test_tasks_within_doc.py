import pytest
from lexicon.tasks import within_doc_findings

def _doc(acceptance, test="a concrete test runs and asserts the result"):
    return ("ARTIFACT: TASKS\nTITLE: t\n\n"
            "TASK: T-001\nPHASE: foundation\nCOMPLEXITY: standard\nPARALLEL: no\n"
            f"REQ: REQ-001\nDEPENDS: none\nACCEPTANCE: {acceptance}\nTEST: {test}\n")

@pytest.mark.unit
def test_banned_word_in_acceptance_flagged():
    f = within_doc_findings(_doc("the system works correctly and is robust"), set())
    assert any(x.code == "banned-word" for x in f)

@pytest.mark.unit
def test_compound_acceptance_not_atomic():
    f = within_doc_findings(_doc("the list renders and the cost panel updates and an email is sent"), set())
    assert any(x.code == "task-not-atomic" for x in f)

@pytest.mark.unit
def test_placeholder_flagged():
    f = within_doc_findings(_doc("renders <TBD> rows"), set())
    assert any(x.code == "incomplete-slot" for x in f)

@pytest.mark.unit
def test_clean_task_has_no_within_doc_findings():
    f = within_doc_findings(_doc("the run list renders one row per discovered run directory"), set())
    assert f == []
