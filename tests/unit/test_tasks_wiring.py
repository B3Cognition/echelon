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
    # Condition aligned to the proven phase1-what shape: the re-dispatch guard
    # references only resolvable keys. The redundant config-namespace conjunct
    # `lexicon_gate.artifacts.tasks.enabled` (which COMMANDER's state evaluator
    # cannot resolve, making the guard indeterminate) must be dropped.
    assert "lexicon_gate.enabled AND NOT tasks_lexicon_pass" in conds
    assert "artifacts.tasks.enabled" not in conds

@pytest.mark.unit
def test_phase3_plan_doc_registers_tasks_lexicon_pass():
    # The phase spec must register `tasks_lexicon_pass` as authoritative state the
    # same way phase1-what.md registers `lexicon_pass`: an explicit controlled-outcome
    # routing instruction to read `state.json.tasks_lexicon_pass`, plus the
    # state_updates contract (tasks_lexicon_pass + tasks_lexicon_attempts).
    txt = pathlib.Path("extension/workflow/phases/phase3-plan.md").read_text()
    assert "state.json.tasks_lexicon_pass" in txt
    assert "tasks_lexicon_attempts" in txt
    assert "Controlled-outcome routing" in txt
