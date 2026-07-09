from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest
import yaml

from harness.docs_verifier import write_docs_verification_report


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "docs_verifier"

PROSAIC_PACKAGE_JSON = """{
  "name": "prosaic",
  "version": "0.1.0",
  "bin": {
    "prosaic": "dist/cli/index.js"
  },
  "engines": {
    "node": ">=20"
  },
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "prepare": "npm run build",
    "test": "jest",
    "lint": "eslint 'src/**/*.ts' 'tests/**/*.ts'",
    "prosaic": "node dist/cli/index.js"
  }
}
"""

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

## Troubleshooting

Run commands from the project root when the dry run creates nothing.

## Develop

```bash
npm run test
```
"""


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
    )


def _commit_all(path: Path, message: str = "base") -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    raw = text.split("---", 2)[1]
    data = yaml.safe_load(raw)
    assert isinstance(data, dict)
    return data


def _write_required_docs(spec_dir: Path) -> None:
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


def _write_keepachangelog(worktree: Path) -> None:
    (worktree / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- Documented first-run Prosaic usage.\n",
        encoding="utf-8",
    )


def test_write_docs_verification_report_passes_first_run_docs(
    tmp_path: Path,
) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{"name":"demo","bin":{"demo":"dist/cli.js"},"engines":{"node":">=20"},"scripts":{"build":"tsc","test":"vitest"}}\n',
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

    result = write_docs_verification_report(tmp_path, spec_dir)

    assert result.verdict == "PASS"
    assert result.blocking_findings == 0
    assert result.report_path == spec_dir / "docs-verification-report.md"
    metadata = _frontmatter(result.report_path)
    assert metadata["verdict"] == "PASS"
    assert metadata["readme_first_run_manual"] is True
    assert metadata["changelog_valid"] is True
    assert metadata["impact_report_valid"] is True
    assert metadata["project_evidence_checked"] is True
    assert metadata["evidence_items_checked"] >= 4
    report = result.report_path.read_text(encoding="utf-8")
    assert "- package.json" in report
    assert "- README.md" in report


def test_prosaic_generated_readme_fixture_fails_first_run_manual(
    tmp_path: Path,
) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-prosaic"
    spec_dir.mkdir(parents=True)
    (tmp_path / "package.json").write_text(PROSAIC_PACKAGE_JSON, encoding="utf-8")
    (tmp_path / "README.md").write_text("# Prosaic\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    poor_readme = FIXTURES / "prosaic-generated-poor-readme.md"
    (tmp_path / "README.md").write_text(
        poor_readme.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_keepachangelog(tmp_path)
    _write_required_docs(spec_dir)

    result = write_docs_verification_report(tmp_path, spec_dir)

    assert result.verdict == "FAIL"
    assert result.readme_first_run_manual is False
    report = result.report_path.read_text(encoding="utf-8")
    assert "README.md is not a first-run manual" in report
    assert "minimal working input" in report
    assert "expected dry-run output" in report
    assert "npm run test:benchmark" in report


def test_prosaic_first_run_manual_fixture_passes_docs_verifier(
    tmp_path: Path,
) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-prosaic"
    spec_dir.mkdir(parents=True)
    (tmp_path / "package.json").write_text(PROSAIC_PACKAGE_JSON, encoding="utf-8")
    (tmp_path / "README.md").write_text("# Prosaic\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    good_readme = FIXTURES / "prosaic-first-run-manual-readme.md"
    (tmp_path / "README.md").write_text(
        good_readme.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_keepachangelog(tmp_path)
    _write_required_docs(spec_dir)

    result = write_docs_verification_report(tmp_path, spec_dir)

    assert result.verdict == "PASS"
    assert result.readme_first_run_manual is True
    assert result.blocking_findings == 0
    metadata = _frontmatter(result.report_path)
    assert metadata["verdict"] == "PASS"


def test_write_docs_verification_report_fails_with_structured_findings(
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

    (tmp_path / "README.md").write_text(
        "# Demo\n\n"
        "Demo distributes files.\n\n"
        "## Install\n\n"
        "```bash\n"
        "npm run missing\n"
        "```\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- Planned: better docs later.\n",
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

    result = write_docs_verification_report(tmp_path, spec_dir)

    assert result.verdict == "FAIL"
    assert result.blocking_findings >= 2
    metadata = _frontmatter(result.report_path)
    assert metadata["verdict"] == "FAIL"
    assert metadata["readme_first_run_manual"] is False
    assert metadata["changelog_valid"] is False
    report = result.report_path.read_text(encoding="utf-8")
    assert "DOCS-001" in report
    assert "README.md" in report
    assert "CHANGELOG.md" in report
    assert "npm run missing" in report


def test_write_docs_verification_report_fails_without_project_evidence(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
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

    result = write_docs_verification_report(tmp_path, spec_dir)

    assert result.verdict == "FAIL"
    assert result.project_evidence_checked is False
    report = result.report_path.read_text(encoding="utf-8")
    assert "Project Evidence" in report


def test_harness_verify_docs_command_writes_pass_report(tmp_path: Path, capsys) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{"name":"demo","bin":{"demo":"dist/cli.js"},"engines":{"node":">=20"},"scripts":{"build":"tsc","test":"vitest"}}\n',
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

    from harness.__main__ import main

    with patch("sys.argv", ["python -m harness", "verify-docs", str(tmp_path), str(spec_dir)]):
        main()

    assert "OK: docs verification PASS" in capsys.readouterr().out
    assert (spec_dir / "docs-verification-report.md").exists()


def test_harness_verify_docs_command_exits_one_on_fail(
    tmp_path: Path,
    capsys,
) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
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

    from harness.__main__ import main

    with patch("sys.argv", ["python -m harness", "verify-docs", str(tmp_path), str(spec_dir)]), \
         pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    assert "docs verification FAIL" in capsys.readouterr().err
    assert (spec_dir / "docs-verification-report.md").exists()
