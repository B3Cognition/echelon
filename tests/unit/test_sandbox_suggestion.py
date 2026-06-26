"""Tests for deterministic sandbox suggestion reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.sandbox_suggestion import (
    SandboxSuggestionReport,
    detect_sandbox_suggestion,
    render_sandbox_suggestion_markdown,
)
from harness.init import _write_sandbox_suggestion_report


@pytest.mark.unit
class TestSandboxSuggestion:
    """Sandbox suggestions are evidence-based and deterministic."""

    def test_high_confidence_report_combines_container_and_test_evidence(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "Dockerfile").write_text(
            "FROM node:20-slim\nEXPOSE 3000\n",
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}),
            encoding="utf-8",
        )
        (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: ci\n", encoding="utf-8")

        report = detect_sandbox_suggestion(tmp_path)

        assert report.confidence_score == 0.95
        assert report.confidence == "high"
        assert "Dockerfile" in report.detected_evidence
        assert "package-lock.json" in report.detected_evidence
        assert ".github/workflows/ci.yml" in report.detected_evidence
        assert report.suggested_strategy == "Use the Docker-backed harness sandbox."
        assert "npm test" in report.suggested_commands
        assert "Build/run app from Dockerfile; target http://localhost:3000." in report.suggested_commands
        assert report.human_approval_point.startswith("Before dependency install")
        assert "review" in report.fallback_path.lower()

    def test_ambiguous_report_requires_manual_approval_before_execution(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}),
            encoding="utf-8",
        )
        (tmp_path / "go.mod").write_text("module example.test/app\ngo 1.22\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("## Setup\nRun npm install.\n", encoding="utf-8")

        report = detect_sandbox_suggestion(tmp_path)

        assert report.confidence == "manual_review"
        assert report.confidence_score == 0.55
        assert report.suggested_commands == []
        assert "package.json scripts.test" in report.detected_evidence
        assert "go.mod" in report.detected_evidence
        assert any("ambiguous" in risk.lower() for risk in report.risks)
        assert "approve" in report.human_approval_point.lower()

    def test_records_readme_setup_instructions_as_evidence(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text(
            "# App\n\n## Setup\n\nRun `npm install` before tests.\n",
            encoding="utf-8",
        )

        report = detect_sandbox_suggestion(tmp_path)

        assert "README.md setup instructions" in report.detected_evidence

    def test_rendered_report_includes_required_sections(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\ndependencies = ['pytest']\n",
            encoding="utf-8",
        )

        report = detect_sandbox_suggestion(tmp_path)
        rendered = render_sandbox_suggestion_markdown(report)

        assert "## Sandbox Suggestion Report" in rendered
        assert "**Confidence:**" in rendered
        assert "### Detected Evidence" in rendered
        assert "### Suggested Commands / Strategy" in rendered
        assert "### Risks" in rendered
        assert "### Human Approval Point" in rendered
        assert "### Fallback Path" in rendered

    def test_init_writer_persists_structured_and_markdown_report(
        self,
        tmp_path: Path,
    ) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  provider: docker\n", encoding="utf-8")
        report = SandboxSuggestionReport(
            confidence="high",
            confidence_score=0.95,
            detected_evidence=["Dockerfile"],
            suggested_strategy="Use the Docker-backed harness sandbox.",
            suggested_commands=["npm test"],
            risks=["Sandbox bind mounts can modify the target worktree."],
            human_approval_point="Approve before execution.",
            fallback_path="Review config manually.",
        )

        _write_sandbox_suggestion_report(config_file, report)

        markdown = config_file.with_name("sandbox-suggestion.md")
        assert markdown.exists()
        assert "## Sandbox Suggestion Report" in markdown.read_text(encoding="utf-8")
