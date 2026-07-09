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


def test_docs_verifier_agent_is_registered() -> None:
    commands = _extension()["provides"]["commands"]
    verifier = next(
        (item for item in commands if item.get("name") == "speckit.echelon.docs-verifier"),
        None,
    )

    assert verifier is not None
    assert verifier["file"] == "agents/build/docs-verifier.md"
    assert "DOCS VERIFIER" in verifier["description"]
    assert verifier["behavior"]["execution"] == "agent"
    assert verifier["behavior"]["tools"] == "write"


def test_tech_writer_phase_is_routed_before_build_finalize() -> None:
    phases = {phase["id"]: phase for phase in _definition()["phases"]}

    docs_phase = phases["build-8-documentation"]
    assert docs_phase["type"] == "agent"
    assert docs_phase["agent"] == "speckit-echelon-tech-writer"
    assert "documentation-impact-report.md" in docs_phase["outputs"]
    assert "shadow_output_recovered" in docs_phase["allowed_state_updates"]
    assert docs_phase["transitions"] == [{"to": "build-8-verify-docs", "condition": "always"}]

    verify_docs = phases["build-8-verify-docs"]
    assert verify_docs["type"] == "agent"
    assert verify_docs["agent"] == "speckit-echelon-docs-verifier"
    assert "docs-verification-report.md" in verify_docs["outputs"]
    assert "documentation-impact-report.md" in verify_docs["context_pack"]
    assert "README.md" in verify_docs["context_pack"]
    assert "CHANGELOG.md" in verify_docs["context_pack"]
    assert verify_docs["transitions"] == [
        {"to": "build-8-finalize", "condition": "verdict = PASS"},
        {"to": "build-8-documentation", "condition": "verdict = FAIL"},
        {"to": "build-8-documentation", "condition": "verdict = BLOCKED"},
    ]

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
    assert "npm run <script>" in text
    assert "package.json" in text
    assert "Avoid product-overview-only README updates" in text


def test_docs_verifier_agent_declares_convergence_contract() -> None:
    text = (ROOT / "extension/agents/build/docs-verifier.md").read_text(
        encoding="utf-8"
    )
    lowered = text.lower()

    assert "DOCS VERIFIER" in text
    assert "README.md" in text
    assert "CHANGELOG.md" in text
    assert "documentation-impact-report.md" in text
    assert "docs-verification-report.md" in text
    assert "readme_first_run_manual" in text
    assert "changelog_valid" in text
    assert "impact_report_valid" in text
    assert "project_evidence_checked" in text
    assert "evidence_items_checked" in text
    assert "blocking_findings" in text
    assert "first-run" in lowered
    assert "safe harness smoke" in lowered
    assert "package.json" in text
    assert "verdict: PASS" in text
    assert "verdict: FAIL" in text
    assert "echelon_result:" in text
    assert "state_updates:" in text


def test_docs_verifier_phase_spec_defines_repair_loop() -> None:
    text = (ROOT / "extension/workflow/phases/build-8-verify-docs.md").read_text(
        encoding="utf-8"
    )

    assert "build-8-documentation" in text
    assert "build-8-finalize" in text
    assert "docs-verification-report.md" in text
    assert "structured repair findings" in text
    assert "safe harness smoke" in text


def test_build_finalize_consumes_documentation_gate() -> None:
    text = (ROOT / "extension/workflow/phases/build-8-finalize.md").read_text(
        encoding="utf-8"
    )

    assert "documentation-impact-report.md" in text
    assert "docs-verification-report.md" in text
    assert "TECH WRITER" in text
    assert "Documentation Convergence Gate" in text
