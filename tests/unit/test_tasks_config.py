import pytest
import yaml

@pytest.mark.unit
def test_lexicon_gate_has_tasks_artifact():
    cfg = yaml.safe_load(open("extension/echelon-config.yml"))
    g = cfg["lexicon_gate"]
    assert g["artifacts"]["tasks"]["enabled"] is True
    assert g["artifacts"]["tasks"]["type"] == "tasks"
    assert g["artifacts"]["tasks"]["spec_ref"] == "requirements.lexicon.md"
    # spec gate validates a derived Lexicon artifact; spec.md remains the rich contract.
    assert g["artifacts"]["spec"]["type"] == "spec"
    assert g["artifacts"]["spec"]["path"] == "requirements.lexicon.md"
    assert g["artifacts"]["spec"]["source_ref"] == "spec.md"
    assert g["artifacts"]["spec"]["mode"] == "derived"
    assert g["on_exhausted"] == "block"
