from pathlib import Path
import subprocess

from harness.documentation_gate import evaluate_documentation_gate


FIRST_RUN_README = """# Demo

Demo distributes project artifacts to local tools.

## Prerequisites

- Node.js 20 or newer.
- npm.

## Install

```bash
npm install
npm run build
npm link
demo --version
```

## First Run

Create `.demo/rules/style.md`:

```markdown
---
description: Shared style.
---

Be concise.
```

Create `demo.config.yaml`:

```yaml
targets:
  - claude-code
```

## Preview the write plan

```bash
demo apply --dry-run
```

Expected output:

```text
Dry run (apply): 1 create, 0 overwrite, 0 backup, 0 remove, 0 unchanged.
create  .claude/style.md [claude-code]
```

## Apply the generated files

```bash
demo apply
```

Expected files:

```text
.claude/style.md
.demo-manifest.json
```

## Revert generated files

```bash
demo revert --dry-run
demo revert
```

## Troubleshooting

Run commands from the project root when the dry run creates nothing.

## Develop

```bash
npm test
npm run lint
```
"""


DOCS_VERIFICATION_PASS = """---
verdict: PASS
readme_first_run_manual: true
changelog_valid: true
impact_report_valid: true
project_evidence_checked: true
evidence_items_checked: 4
blocking_findings: 0
---

# Docs Verification Report

## Verdict

PASS
"""


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _commit_all(path: Path, message: str = "base") -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)


def _write_docs_verification_pass(spec_dir: Path) -> None:
    (spec_dir / "docs-verification-report.md").write_text(
        DOCS_VERIFICATION_PASS,
        encoding="utf-8",
    )


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

    (tmp_path / "README.md").write_text(FIRST_RUN_README, encoding="utf-8")
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
    _write_docs_verification_pass(spec_dir)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert result.passed


def test_gate_accepts_required_docs_changed_in_delivery_slice(tmp_path: Path) -> None:
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
    (tmp_path / "package.json").write_text(
        '{"name":"demo","bin":{"demo":"dist/cli.js"},"engines":{"node":">=20"},"scripts":{"build":"tsc","test":"vitest","lint":"eslint ."}}\n',
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    (tmp_path / "README.md").write_text(FIRST_RUN_README, encoding="utf-8")
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
    _write_docs_verification_pass(spec_dir)
    _commit_all(tmp_path, "docs update")
    (spec_dir / "echelon-result.json").write_text('{"status":"done"}\n', encoding="utf-8")
    _commit_all(tmp_path, "status update")

    result = evaluate_documentation_gate(
        tmp_path,
        spec_dir,
        changed_files=["README.md", "CHANGELOG.md"],
    )

    assert result.passed


def test_gate_blocks_required_docs_without_docs_verification_report(
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
    _commit_all(tmp_path)

    (tmp_path / "README.md").write_text(FIRST_RUN_README, encoding="utf-8")
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

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "docs-verification-report-missing"


def test_gate_blocks_required_docs_when_docs_verifier_failed(tmp_path: Path) -> None:
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

    (tmp_path / "README.md").write_text(FIRST_RUN_README, encoding="utf-8")
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
    (spec_dir / "docs-verification-report.md").write_text(
        "---\n"
        "verdict: FAIL\n"
        "readme_first_run_manual: false\n"
        "changelog_valid: true\n"
        "impact_report_valid: true\n"
        "blocking_findings: 1\n"
        "---\n"
        "# Docs Verification Report\n",
        encoding="utf-8",
    )

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "docs-verification-report-failed"


def test_gate_blocks_docs_verifier_pass_without_project_evidence(
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
    _commit_all(tmp_path)

    (tmp_path / "README.md").write_text(FIRST_RUN_README, encoding="utf-8")
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
    (spec_dir / "docs-verification-report.md").write_text(
        "---\n"
        "verdict: PASS\n"
        "readme_first_run_manual: true\n"
        "changelog_valid: true\n"
        "impact_report_valid: true\n"
        "blocking_findings: 0\n"
        "---\n"
        "# Docs Verification Report\n",
        encoding="utf-8",
    )

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "docs-verification-report-invalid"
    assert "project_evidence_checked" in result.failure.error


def test_gate_blocks_overview_only_readme_for_required_cli_docs(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{"name":"demo","bin":{"demo":"dist/cli.js"},"engines":{"node":">=20"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    (tmp_path / "README.md").write_text(
        "# Demo\n\n"
        "Demo is a distribution engine.\n\n"
        "## Install\n\n"
        "```bash\n"
        "npm install -g demo\n"
        "```\n\n"
        "## Use\n\n"
        "```bash\n"
        "demo apply --dry-run\n"
        "demo apply\n"
        "```\n\n"
        "## Configuration\n\n"
        "Create `demo.config.yaml`.\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- Documented the CLI.\n",
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
    _write_docs_verification_pass(spec_dir)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "readme-first-run-manual-incomplete"
    assert "Prerequisites" in result.failure.error
    assert "minimal working input" in result.failure.error
    assert "expected dry-run output" in result.failure.error


def test_gate_blocks_changelog_planned_entries_for_required_docs(tmp_path: Path) -> None:
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

    (tmp_path / "README.md").write_text(FIRST_RUN_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- Planned: watch mode will be added later.\n",
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
    _write_docs_verification_pass(spec_dir)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "changelog-planned-entry"


def test_gate_blocks_readme_npm_script_commands_missing_from_package_json(
    tmp_path: Path,
) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{"name":"demo","bin":{"demo":"dist/cli.js"},"engines":{"node":">=20"},"scripts":{"build":"tsc"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    (tmp_path / "README.md").write_text(FIRST_RUN_README, encoding="utf-8")
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
    _write_docs_verification_pass(spec_dir)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "readme-command-claim-unsupported"
    assert "npm test" in result.failure.error
    assert "npm run lint" in result.failure.error
