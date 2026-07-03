from pathlib import Path
import subprocess

from harness.documentation_gate import evaluate_documentation_gate


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _commit_all(path: Path, message: str = "base") -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)


def test_gate_blocks_missing_report(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    _commit_all(tmp_path)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "documentation-impact-report-missing"


def test_gate_accepts_not_applicable_report_with_reason(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: false\n"
        "readme_updated: false\n"
        "changelog_updated: false\n"
        "changelog_format: not_required\n"
        'not_applicable_reason: "Only internal tests changed."\n'
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert result.passed


def test_gate_blocks_required_docs_without_readme_and_changelog_changes(
    tmp_path: Path,
) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: true\n"
        "readme_updated: true\n"
        "changelog_updated: true\n"
        "changelog_format: keep_a_changelog\n"
        'not_applicable_reason: ""\n'
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "documentation-required-without-doc-changes"


def test_gate_accepts_required_docs_with_keepachangelog_changes(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    (tmp_path / "README.md").write_text(
        "# Demo\n\nNew documented behavior.\n", encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- Documented new behavior.\n",
        encoding="utf-8",
    )
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: true\n"
        "readme_updated: true\n"
        "changelog_updated: true\n"
        "changelog_format: keep_a_changelog\n"
        'not_applicable_reason: ""\n'
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert result.passed
