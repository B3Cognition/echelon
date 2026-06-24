from pathlib import Path

import yaml

from harness.role_contracts import (
    validate_agent_result_contract,
    validate_role_contracts,
)


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "extension/workflow/definition.yaml"
EXT_YML = ROOT / "extension/extension.yml"


def _write_fixture_extension(root: Path, agent_text: str, outputs=None) -> tuple[Path, Path]:
    agents_dir = root / "agents"
    agents_dir.mkdir()
    (agents_dir / "scout.md").write_text(agent_text, encoding="utf-8")

    extension_yml = root / "extension.yml"
    extension_yml.write_text(
        yaml.safe_dump(
            {
                "provides": {
                    "commands": [
                        {
                            "name": "speckit.echelon.scout",
                            "file": "agents/scout.md",
                            "behavior": {"execution": "agent"},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    phase = {
        "id": "phase1-discover",
        "type": "agent",
        "agent": "speckit-echelon-scout",
        "transitions": [{"to": "done", "condition": "always"}],
    }
    if outputs is not None:
        phase["outputs"] = outputs

    definition = root / "definition.yaml"
    definition.write_text(
        yaml.safe_dump({"phases": [phase]}),
        encoding="utf-8",
    )
    return definition, extension_yml


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
    definition, extension_yml = _write_fixture_extension(
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
        extension_yml_path=extension_yml,
        extension_root=tmp_path,
    )

    assert not report.ok
    assert any("declared outputs" in issue.message for issue in report.issues)


def test_role_contract_validation_reports_missing_state_update_allowlist(
    tmp_path: Path,
) -> None:
    definition, extension_yml = _write_fixture_extension(
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
        extension_yml_path=extension_yml,
        extension_root=tmp_path,
    )

    assert not report.ok
    assert any("state_updates allowlist" in issue.message for issue in report.issues)


def test_real_routed_roles_have_machine_readable_contracts() -> None:
    report = validate_role_contracts(
        definition_path=DEFINITION,
        extension_yml_path=EXT_YML,
        extension_root=ROOT / "extension",
    )

    assert report.ok, report.format()
