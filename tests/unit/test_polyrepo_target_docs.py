from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_readme_documents_polyrepo_target_preflight() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "echelon delivery run 001 --mode semi" in text
    assert "echelon delivery run 001 --mode banzai" in text
    assert "source root" in text
    assert "lands the target repo branch" in text


@pytest.mark.unit
def test_readme_documents_the_first_spec_path() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "### First spec in a new or existing workspace" in text
    assert "specify init --here --integration claude --offline" in text
    assert "specify extension add --force --dev ~/echelon/extension" in text
    assert "echelon workspace init" in text
    assert "echelon workspace sources sync --write" in text
    assert 'echelon spec run "Create a sample Hello World program in Python"' in text


@pytest.mark.unit
def test_harness_command_docs_document_target_preflight_and_recovery() -> None:
    run_doc = (ROOT / "extension/commands/echelon.harness-run.md").read_text(
        encoding="utf-8"
    )
    resume_doc = (ROOT / "extension/commands/echelon.harness-resume.md").read_text(
        encoding="utf-8"
    )

    assert "targets.yml` is authoritative" in run_doc
    assert "source root" in run_doc
    assert "echelon spec run <description> --target <source-path>" in run_doc
    assert "never establish it" in run_doc
    assert "recorded target repo metadata" in resume_doc
    assert "build_incomplete" in resume_doc


@pytest.mark.unit
def test_harness_command_docs_do_not_expose_harness_source_dir() -> None:
    run_doc = (ROOT / "extension/commands/echelon.harness-run.md").read_text(
        encoding="utf-8"
    )

    assert "HARNESS_SOURCE_DIR" not in run_doc
    assert "read files there" not in run_doc
    assert "Do not inspect, read, or search for harness source" in run_doc


@pytest.mark.unit
def test_harness_compatibility_docs_point_to_delivery_commands() -> None:
    docs = {
        "run": (ROOT / "extension/commands/echelon.harness-run.md").read_text(
            encoding="utf-8"
        ),
        "resume": (ROOT / "extension/commands/echelon.harness-resume.md").read_text(
            encoding="utf-8"
        ),
        "status": (ROOT / "extension/commands/echelon.harness-status.md").read_text(
            encoding="utf-8"
        ),
    }

    assert "echelon delivery init" in docs["run"]
    assert "echelon delivery run <spec_id>" in docs["run"]
    assert "echelon delivery resume <spec_id>" in docs["resume"]
    assert "echelon delivery status" in docs["status"]
    for text in docs.values():
        assert "speckit.echelon.harness-init" not in text
        assert "speckit.echelon.harness-run" not in text
        assert "speckit.echelon.harness-resume" not in text
        assert "speckit.echelon.harness-status" not in text


@pytest.mark.unit
def test_workspace_model_docs_define_single_repo_as_one_source_root() -> None:
    text = (ROOT / "docs/workspace-model.md").read_text(encoding="utf-8")

    assert "sources: [.]" in text
    assert "lightweight workspace Git repo" in text
    assert "branchless workspace" in text
    assert "echelon workspace migrate" in text
    assert "echelon spec run \"Describe the feature\" --target og-platform" in text
    assert "echelon spec run \"Create the new tool\" --target sources/new-tool --init" in text

    assert (ROOT / "extension/scripts/python/migrate_workspace_git.py").exists()


@pytest.mark.unit
def test_re_docs_use_workspace_source_roots_not_monorepo_of_monorepos() -> None:
    text = (ROOT / "docs/re-overview.md").read_text(encoding="utf-8")

    assert "workspace-manifest.json" in text
    assert "source roots" in text
    assert "monorepo of monorepos" not in text
