import pytest, pathlib

@pytest.mark.unit
def test_template_has_test_field():
    txt = pathlib.Path("extension/templates/tasks-template.md").read_text()
    assert "**Test:**" in txt
    assert "- [ ] T-001" in txt  # canonical row still present

@pytest.mark.unit
def test_orchestrator_authors_canonical_rows():
    txt = pathlib.Path("extension/agents/solution/orchestrator.md").read_text()
    assert "canonical" in txt.lower() and "**Test:**" in txt
    assert "ARTIFACT: TASKS" not in txt   # block grammar instruction removed
    assert "controller validates" in txt
    assert "--type tasks" not in txt
