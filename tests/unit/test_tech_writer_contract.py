from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _extension() -> dict:
    return yaml.safe_load((ROOT / "extension/extension.yml").read_text(encoding="utf-8"))


def _definition() -> dict:
    return yaml.safe_load(
        (ROOT / "extension/workflow/definition.yaml").read_text(encoding="utf-8")
    )


def test_tech_writer_agent_is_registered() -> None:
    commands = _extension()["provides"]["commands"]
    tech_writer = next(
        (item for item in commands if item.get("name") == "speckit.echelon.tech-writer"),
        None,
    )

    assert tech_writer is not None
    assert tech_writer["file"] == "agents/build/tech-writer.md"
    assert "TECH WRITER" in tech_writer["description"]
    assert tech_writer["behavior"]["execution"] == "agent"
    assert tech_writer["behavior"]["tools"] == "write"


def test_tech_writer_phase_is_routed_before_build_finalize() -> None:
    phases = {phase["id"]: phase for phase in _definition()["phases"]}

    docs_phase = phases["build-8-documentation"]
    assert docs_phase["type"] == "agent"
    assert docs_phase["agent"] == "speckit-echelon-tech-writer"
    assert "documentation-impact-report.md" in docs_phase["outputs"]
    assert "shadow_output_recovered" in docs_phase["allowed_state_updates"]
    assert docs_phase["transitions"] == [{"to": "build-8-finalize", "condition": "always"}]

    progress_targets = {
        transition["to"]
        for transition in phases["build-6-progress"]["transitions"]
        if transition.get("condition") == "all_tasks_complete AND no_more_phase_checkpoints"
    }
    integration_targets = {
        transition["to"]
        for transition in phases["build-7-integration"]["transitions"]
        if transition.get("condition") == "verdict = PASS AND all_phase_groups_complete"
    }
    assert progress_targets == {"build-8-documentation"}
    assert integration_targets == {"build-8-documentation"}


def test_tech_writer_agent_declares_required_result_contract() -> None:
    text = (ROOT / "extension/agents/build/tech-writer.md").read_text(encoding="utf-8")

    assert "ALWAYS" in text
    assert "NEVER" in text
    assert "README.md" in text
    assert "CHANGELOG.md" in text
    assert "Keep a Changelog" in text
    assert "documentation-impact-report.md" in text
    assert "echelon_result:" in text
    assert "  verdict:" in text
    assert "  output_files:" in text
    assert "  state_updates:" in text
    assert "  journal_entries:" in text


def test_tech_writer_readme_contract_requires_first_run_manual() -> None:
    text = (ROOT / "extension/agents/build/tech-writer.md").read_text(encoding="utf-8")
    lowered = text.lower()

    assert "README First-Run Manual Contract" in text
    assert "first-time local user" in lowered
    assert "prerequisites" in lowered
    assert "minimal working configuration" in lowered
    assert "first dry run" in lowered
    assert "first real run" in lowered
    assert "expected output" in lowered
    assert "troubleshooting" in lowered
    assert "Avoid product-overview-only README updates" in text


def test_build_finalize_consumes_documentation_gate() -> None:
    text = (ROOT / "extension/workflow/phases/build-8-finalize.md").read_text(
        encoding="utf-8"
    )

    assert "documentation-impact-report.md" in text
    assert "TECH WRITER" in text
    assert "Documentation Currency Gate" in text
