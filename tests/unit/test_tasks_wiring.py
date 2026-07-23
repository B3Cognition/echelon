import pytest, yaml, pathlib

@pytest.mark.unit
def test_orchestrator_has_tasks_gate_mode():
    txt = pathlib.Path("extension/agents/solution/orchestrator.md").read_text()
    assert "Tasks Gate Mode" in txt
    assert "canonical row format" in txt
    assert "controller validates" in txt
    assert "lexicon validate" not in txt
    assert "Do not report `tasks_lexicon_pass`" in txt

@pytest.mark.unit
def test_phase3_plan_redispatch_transition():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    nodes = {node["id"]: node for node in d["phases"]}
    assert nodes["phase3-plan"]["transitions"] == [
        {"to": "phase3-tasks-lexicon", "condition": "always"}
    ]
    gate = nodes["phase3-tasks-lexicon"]
    assert gate["type"] == "deterministic_lexicon"
    assert gate["lexicon_artifact"] == "tasks"
    assert gate["transitions"] == [
        {
            "to": "phase3-plan",
            "condition": "tasks_lexicon_action = repair",
            "action": "increment_iteration",
        },
        {
            "to": "terminal-blocked",
            "condition": "tasks_lexicon_action = block",
        },
        {
            "to": "phase3-understanding",
            "condition": (
                "tasks_lexicon_action in [proceed, proceed_with_warning]"
            ),
        },
    ]

@pytest.mark.unit
def test_phase3_plan_doc_declares_controller_owned_tasks_gate():
    txt = pathlib.Path("extension/workflow/phases/phase3-plan.md").read_text()
    assert "state.json.tasks_lexicon_pass" in txt
    assert "tasks_lexicon_attempts" in txt
    assert "controller validates" in txt
    assert "lexicon validate" not in txt
    assert "tasks-lexicon-report.json" in txt
    assert "python -m harness" not in txt


@pytest.mark.unit
def test_phase3_consensus_recertifies_plan2_tasks():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    nodes = {node["id"]: node for node in d["phases"]}
    assert nodes["phase3-consensus"]["transitions"] == [
        {
            "to": "phase3-consensus-tasks-lexicon",
            "condition": "always",
        }
    ]
    gate = nodes["phase3-consensus-tasks-lexicon"]
    assert gate["type"] == "deterministic_lexicon"
    assert gate["lexicon_artifact"] == "tasks"
    conds = " ".join(t.get("condition", "") for t in gate["transitions"])
    assert "tasks_lexicon_action = repair" in conds
    assert "tasks_lexicon_action = block" in conds
    assert "why3-verdict = FAIL" in conds
    assert "assess2-verdict = REJECTED" in conds
