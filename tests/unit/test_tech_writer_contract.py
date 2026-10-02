from pathlib import Path

import yaml

from harness.prompt_markdown import read_prompt_markdown


ROOT = Path(__file__).resolve().parents[2]


def _agent_metadata(name: str) -> dict:
    return read_prompt_markdown(
        ROOT / "prosaic" / "subagents" / f"echelon.{name}.md"
    ).metadata


def _definition() -> dict:
    return yaml.safe_load(
        (ROOT / "runtime/workflow/definition.yaml").read_text(encoding="utf-8")
    )


def test_tech_writer_agent_has_canonical_prosaic_metadata() -> None:
    tech_writer = _agent_metadata("tech-writer")

    assert tech_writer["name"] == "echelon.tech-writer"
    assert "TECH WRITER" in tech_writer["description"]
    assert tech_writer["execution"] == "agent"
    assert tech_writer["tools"] == "write"


def test_docs_verifier_agent_has_canonical_prosaic_metadata() -> None:
    verifier = _agent_metadata("docs-verifier")

    assert verifier["name"] == "echelon.docs-verifier"
    assert "DOCS VERIFIER" in verifier["description"]
    assert verifier["execution"] == "agent"
    assert verifier["tools"] == "write"


def test_delivery_documentation_uses_controller_roles_not_retired_graph_routes() -> None:
    from harness.delivery_documentation_contract import STEPS

    phases = {phase["id"]: phase for phase in _definition()["phases"]}
    assert not {phase for phase in phases if phase.startswith("build-")}
    assert STEPS == ("tech_writer", "docs_verifier")
    for role, tools in (("delivery-tech-writer", "write"), ("delivery-docs-verifier", "read")):
        metadata = _agent_metadata(role)
        assert metadata["name"] == f"echelon.{role}"
        assert metadata["execution"] == "agent"
        assert metadata["tools"] == tools


def test_tech_writer_agent_declares_required_result_contract() -> None:
    text = (ROOT / "prosaic/subagents/echelon.tech-writer.md").read_text(encoding="utf-8")

    assert "ALWAYS" in text
    assert "NEVER" in text
    assert "README.md" in text
    assert "CHANGELOG.md" in text
    assert "Keep a Changelog" in text
    assert "documentation-impact-report.md" in text
    assert "schema_version: 2" in text
    assert "delivery_change_ids" in text
    assert "documented_changes" in text
    assert "evidence_paths" in text
    assert "disposition" in text
    assert "echelon_result:" in text
    assert "  verdict:" in text
    assert "  output_files:" in text
    assert "  state_updates:" in text
    assert "  journal_entries:" in text


def test_tech_writer_readme_contract_requires_first_run_manual() -> None:
    text = (ROOT / "prosaic/subagents/echelon.tech-writer.md").read_text(encoding="utf-8")
    lowered = text.lower()

    assert "README First-Run Manual Contract" in text
    assert "first-time local user" in lowered
    assert "prerequisites" in lowered
    assert "minimal working configuration" in lowered
    assert "first dry run" in lowered
    assert "first real run" in lowered
    assert "expected output" in lowered
    assert "troubleshooting" in lowered
    assert "package.json" in text
    assert "Avoid product-overview-only README updates" in text


def test_docs_verifier_agent_declares_convergence_contract() -> None:
    text = (ROOT / "prosaic/subagents/echelon.docs-verifier.md").read_text(
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
    assert "schema_version: 2" in text
    assert "reviewed_change_ids" in text
    assert "uncovered_change_ids" in text
    assert "unsupported_claims" in text
    assert "python -m harness verify-docs" in text
    assert "first-run" in lowered
    assert "safe harness smoke" in lowered
    assert "package.json" in text
    assert "verdict: PASS" in text
    assert "verdict: FAIL" in text
    assert "echelon_result:" in text
    assert "state_updates:" in text


def test_delivery_docs_verifier_returns_findings_without_owning_repair_routing() -> None:
    text = (ROOT / "prosaic/subagents/echelon.delivery-docs-verifier.md").read_text(
        encoding="utf-8"
    )
    assert "Required Repair" in text
    assert "source evidence and concrete required repair" in text
    assert "report_markdown" in text
    assert "assignment-bound JSON" in text
    assert "verdict PASS/FAIL/BLOCKED" in text
    assert "prescribe retries, publication or workflow routing" in text
    assert not (ROOT / "runtime/workflow/phases/build-8-verify-docs.md").exists()


def test_delivery_documentation_keeps_report_publication_under_controller_ownership() -> None:
    from harness.delivery_documentation_contract import DOCS, REPORTS

    assert DOCS == ("README.md", "CHANGELOG.md")
    assert REPORTS == ("documentation-impact-report.md", "docs-verification-report.md")
    writer = (ROOT / "prosaic/subagents/echelon.delivery-tech-writer.md").read_text(encoding="utf-8")
    verifier = (ROOT / "prosaic/subagents/echelon.delivery-docs-verifier.md").read_text(encoding="utf-8")
    assert "publishes the" in writer and "canonical Spec report only after a passing review and deterministic gate" in writer
    assert "NEVER write the report to disk" in writer
    assert "ALWAYS operate read-only and return the report text" in verifier
    assert "staged_not_published" in verifier
    assert not (ROOT / "runtime/workflow/phases/build-8-finalize.md").exists()


def test_tech_writer_uses_current_runnability_evidence_without_inventing_commands() -> None:
    text = (ROOT / "prosaic/subagents/echelon.tech-writer.md").read_text(
        encoding="utf-8"
    )

    assert ".echelon/runnability.yml" in text
    assert "user-runnability" in text
    assert "exact" in text.lower()
    assert "NEVER invent" in text


def test_docs_verifier_requires_current_runnability_digest_for_final_pass() -> None:
    text = (ROOT / "prosaic/subagents/echelon.docs-verifier.md").read_text(
        encoding="utf-8"
    )

    assert "runnability_evidence_sha256" in text
    assert "runnability_commands_current" in text
    assert "NEVER pass" in text
    assert "provisional" in text.lower()


def test_delivery_docs_verifier_blocks_missing_failed_stale_or_provisional_runnability() -> None:
    text = (ROOT / "prosaic/subagents/echelon.delivery-docs-verifier.md").read_text(
        encoding="utf-8"
    )

    assert "current immutable passing runnability report" in text
    for state in ("missing", "failed", "stale", "provisional"):
        assert state in text.lower()
    assert "commands_current must be true" in text
    assert "evidence digest" in text
    assert "exactly match the supplied current report" in text
