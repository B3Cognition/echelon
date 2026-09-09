from pathlib import Path

import pytest

from harness.phase3_repair import RepairContractError
from harness.phase3_repair_context import capture_repair_context, capture_review_inputs


def test_review_includes_architecture_and_nested_contracts(tmp_path):
    (tmp_path / "spec.md").write_text("Required behavior")
    (tmp_path / "architecture.md").write_text("Component authority")
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "api.md").write_text("Read boundary")
    manifest, context = capture_review_inputs(tmp_path, project_root=tmp_path)
    assert "architecture.md" in manifest
    assert "Component authority" in context
    assert "contracts/api.md" in manifest


@pytest.mark.parametrize("case", ["missing", "overflow", "symlink", "parent_symlink"])
def test_required_repair_context_fails_closed(tmp_path, case):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "spec.md").write_text("Required behavior")
    if case == "overflow":
        (spec / "issues.md").write_text("x" * 262145)
    elif case == "symlink":
        (spec / "issues.md").symlink_to(spec / "spec.md")
    elif case == "parent_symlink":
        (spec / "issues.md").write_text("Current issues")
        (spec / "contracts").mkdir()
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "api.md").write_text("Outside owned contract tree")
        (spec / "contracts" / "linked").symlink_to(tmp_path / "shared", target_is_directory=True)
    with pytest.raises(RepairContractError):
        capture_repair_context(spec, project_root=tmp_path)


def test_workflow_how_receives_consensus_journal():
    import yaml
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / "runtime/workflow/definition.yaml").read_text())
    how = next(p for p in workflow["phases"] if p["id"] == "phase3-how")
    assert any("phase=phase3-consensus" in source for source in how["context_pack"])
