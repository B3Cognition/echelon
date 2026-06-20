import pytest, yaml, pathlib

@pytest.mark.unit
def test_orchestrator_has_tasks_gate_mode():
    txt = pathlib.Path("extension/agents/solution/orchestrator.md").read_text()
    assert "Tasks Gate Mode" in txt
    assert "lexicon validate" in txt and "--type tasks" in txt
    assert "tasks_lexicon_pass" in txt
    assert "--spec-ref" in txt

@pytest.mark.unit
def test_phase3_plan_redispatch_transition():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase3-plan")
    conds = " ".join(t.get("condition","") for t in node["transitions"])
    assert "tasks_lexicon_pass" in conds and "NOT tasks_lexicon_pass" in conds
