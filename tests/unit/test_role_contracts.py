from pathlib import Path

import yaml

from harness.role_contracts import (
    validate_agent_result_contract,
    validate_role_contracts,
)


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "runtime/workflow/definition.yaml"
PROSAIC_SUBAGENTS = ROOT / "prosaic/subagents"


def _write_fixture_prosaic(root: Path, agent_text: str, outputs=None) -> tuple[Path, Path]:
    subagents_dir = root / "subagents"
    subagents_dir.mkdir()
    (subagents_dir / "echelon.scout.md").write_text(agent_text, encoding="utf-8")

    phase = {
        "id": "phase1-discover",
        "type": "agent",
        "agent": "echelon-scout",
        "transitions": [{"to": "done", "condition": "always"}],
    }
    if outputs is not None:
        phase["outputs"] = outputs

    definition = root / "definition.yaml"
    definition.write_text(
        yaml.safe_dump({"phases": [phase]}),
        encoding="utf-8",
    )
    return definition, subagents_dir


def test_agent_result_contract_accepts_complete_template() -> None:
    issues = validate_agent_result_contract(
        """
## Output Block

echelon_result:
  verdict: COMPLETE
  output_files:
    - {spec_dir}/artifact.md
  state_updates: {}
  journal_entries: []
"""
    )

    assert issues == []


def test_agent_result_contract_requires_machine_readable_fields() -> None:
    issues = validate_agent_result_contract(
        """
echelon_result:
  verdict: COMPLETE
  output_files:
    - {spec_dir}/artifact.md
  journal_entries: []
"""
    )

    assert any("state_updates" in issue.message for issue in issues)


def test_role_contract_validation_reports_missing_phase_outputs(tmp_path: Path) -> None:
    definition, subagents_dir = _write_fixture_prosaic(
        tmp_path,
        """
echelon_result:
  verdict: COMPLETE
  output_files:
    - {spec_dir}/artifact.md
  state_updates: {}
  journal_entries: []
""",
    )

    report = validate_role_contracts(
        definition_path=definition,
        prosaic_subagents_dir=subagents_dir,
    )

    assert not report.ok
    assert any("declared outputs" in issue.message for issue in report.issues)


def test_role_contract_validation_reports_missing_state_update_allowlist(
    tmp_path: Path,
) -> None:
    definition, subagents_dir = _write_fixture_prosaic(
        tmp_path,
        """
echelon_result:
  verdict: COMPLETE
  output_files:
    - {spec_dir}/artifact.md
  state_updates: {}
  journal_entries: []
""",
        outputs=["artifact.md"],
    )

    report = validate_role_contracts(
        definition_path=definition,
        prosaic_subagents_dir=subagents_dir,
    )

    assert not report.ok
    assert any("state_updates allowlist" in issue.message for issue in report.issues)


def test_real_routed_roles_have_machine_readable_contracts() -> None:
    report = validate_role_contracts(
        definition_path=DEFINITION,
        prosaic_subagents_dir=PROSAIC_SUBAGENTS,
    )

    assert report.ok, report.format()
