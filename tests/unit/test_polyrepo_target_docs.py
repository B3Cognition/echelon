from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_readme_documents_polyrepo_target_preflight() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "echelon harness run 001 mode=semi" in text
    assert "echelon harness run 001 mode=banzai" in text
    assert "lands the target repo branch" in text


@pytest.mark.unit
def test_harness_command_docs_document_target_preflight_and_recovery() -> None:
    run_doc = (ROOT / "extension/commands/echelon.harness-run.md").read_text(
        encoding="utf-8"
    )
    resume_doc = (ROOT / "extension/commands/echelon.harness-resume.md").read_text(
        encoding="utf-8"
    )

    assert "deterministic target detection" in run_doc
    assert "echelon spec target <spec_id> <repo>" in run_doc
    assert "recorded target repo metadata" in resume_doc
    assert "build_incomplete" in resume_doc
