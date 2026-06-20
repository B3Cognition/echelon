import pytest
import yaml

@pytest.mark.unit
def test_lexicon_gate_has_tasks_artifact():
    cfg = yaml.safe_load(open("extension/echelon-config.yml"))
    g = cfg["lexicon_gate"]
    assert g["artifacts"]["tasks"]["enabled"] is True
    assert g["artifacts"]["tasks"]["type"] == "tasks"
    assert g["artifacts"]["tasks"]["spec_ref"] == "spec.md"
    # spec entry still present (back-compat)
    assert g["artifacts"]["spec"]["type"] == "spec"
