from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_readme_documents_polyrepo_target_preflight() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "echelon harness run 001 mode=semi" in text
    assert "echelon harness run 001 mode=banzai" in text
    assert "source root" in text
    assert "lands the target repo branch" in text


@pytest.mark.unit
def test_harness_command_docs_document_target_preflight_and_recovery() -> None:
    run_doc = (ROOT / "extension/commands/echelon.harness-run.md").read_text(
        encoding="utf-8"
    )
    resume_doc = (ROOT / "extension/commands/echelon.harness-resume.md").read_text(
        encoding="utf-8"
    )

    assert "resolves source roots" in run_doc
    assert "source root" in run_doc
    assert "echelon spec target <spec_id> <source-path>" in run_doc
    assert "recorded target repo metadata" in resume_doc
    assert "build_incomplete" in resume_doc


@pytest.mark.unit
def test_workspace_model_docs_define_single_repo_as_one_source_root() -> None:
    text = (ROOT / "docs/workspace-model.md").read_text(encoding="utf-8")

    assert "sources: [.]" in text
    assert "lightweight workspace Git repo" in text
    assert "branchless workspace" in text
    assert ".specify/extensions/echelon/scripts/python/migrate_workspace_git.py" in text
    assert "echelon spec target" in text

    assert (ROOT / "extension/scripts/python/migrate_workspace_git.py").exists()


@pytest.mark.unit
def test_re_docs_use_workspace_source_roots_not_monorepo_of_monorepos() -> None:
    text = (ROOT / "docs/re-overview.md").read_text(encoding="utf-8")

    assert "workspace-manifest.json" in text
    assert "source roots" in text
    assert "monorepo of monorepos" not in text
