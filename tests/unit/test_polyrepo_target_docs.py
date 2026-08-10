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
    assert "echelon workspace init --llm claude" in text
    assert ".echelon/prosaic/" in text
    assert "specify init --here" not in text
    assert "echelon workspace sources sync --write" in text
    assert 'echelon spec run "Create a sample Hello World program in Python"' in text


@pytest.mark.unit
def test_readme_advises_workspace_commands_for_source_configuration() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Rather than editing `sources:` by hand" in text
    assert "echelon workspace sources sync" in text
    assert "echelon workspace sources sync --write" in text
    assert "echelon workspace doctor" in text
    assert "echelon workspace migrate --write" in text


@pytest.mark.unit
def test_readme_installation_and_configuration_docs_use_current_contract() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "INSTALLATION.md").read_text(encoding="utf-8")

    assert "Node.js with npm is\noptional" in text
    assert "echelon delivery run 001 --strategy codegen" in text
    assert "`.echelon/config.yml`" in text
    assert "`echelon-config.yml`" not in text
    assert "config-template.yml" not in text
    assert "run spec 001-photo-album" not in text
    assert "Node.js with npm is optional" in installation
    assert "echelon workspace init --llm claude" in installation
    assert "specify extension add --force --dev ~/echelon/extension" not in installation
    assert "`echelon-config.yml`" not in installation


@pytest.mark.unit
def test_harness_command_docs_delegate_target_preflight_and_recovery() -> None:
    run_doc = (ROOT / "prosaic/commands/echelon.harness-run.md").read_text(
        encoding="utf-8"
    )
    resume_doc = (ROOT / "prosaic/commands/echelon.harness-resume.md").read_text(
        encoding="utf-8"
    )

    assert "controller owns target resolution" in run_doc.lower()
    assert "recovery" in run_doc
    assert "Do not reproduce those operations" in run_doc
    assert "controller owns state validation and recovery" in resume_doc.lower()
    assert "Do not inspect or edit controller state directly" in resume_doc


@pytest.mark.unit
def test_harness_command_docs_do_not_expose_harness_source_dir() -> None:
    run_doc = (ROOT / "prosaic/commands/echelon.harness-run.md").read_text(
        encoding="utf-8"
    )

    assert "HARNESS_SOURCE_DIR" not in run_doc
    assert "read files there" not in run_doc
    assert "Do not reproduce those operations" in run_doc
    assert "without attempting manual Git or state repair" in run_doc


@pytest.mark.unit
def test_harness_compatibility_docs_point_to_delivery_commands() -> None:
    docs = {
        "run": (ROOT / "prosaic/commands/echelon.harness-run.md").read_text(
            encoding="utf-8"
        ),
        "resume": (ROOT / "prosaic/commands/echelon.harness-resume.md").read_text(
            encoding="utf-8"
        ),
        "status": (ROOT / "prosaic/commands/echelon.harness-status.md").read_text(
            encoding="utf-8"
        ),
    }

    assert "echelon delivery init" in docs["run"]
    assert "echelon delivery run {{args}}" in docs["run"]
    assert "echelon delivery resume {{args}}" in docs["resume"]
    assert "echelon delivery status {{args}}" in docs["status"]


@pytest.mark.unit
def test_workspace_model_docs_define_single_repo_as_one_source_root() -> None:
    text = (ROOT / "docs/workspace-model.md").read_text(encoding="utf-8")

    assert "sources: [.]" in text
    assert "lightweight workspace Git repo" in text
    assert "branchless workspace" in text
    assert "echelon workspace migrate" in text
    assert "echelon spec run \"Describe the feature\" --target og-platform" in text
    assert "echelon spec run \"Create the new tool\" --target sources/new-tool --init" in text

    assert (ROOT / "runtime/scripts/python/migrate_workspace_git.py").exists()


@pytest.mark.unit
def test_re_docs_use_workspace_source_roots_not_monorepo_of_monorepos() -> None:
    text = (ROOT / "docs/re-overview.md").read_text(encoding="utf-8")

    assert "workspace-manifest.json" in text
    assert "source roots" in text
    assert "monorepo of monorepos" not in text
