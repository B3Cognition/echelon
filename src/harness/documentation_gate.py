"""Deterministic README/CHANGELOG currency gate for harness builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

import yaml

from harness.verify_result import FailureCategory, FailureEntry


REPORT_NAME = "documentation-impact-report.md"
CHANGELOG_CATEGORIES = (
    "Added",
    "Changed",
    "Fixed",
    "Performance",
    "Security",
    "Deprecated",
    "Removed",
)


@dataclass(frozen=True)
class DocumentationGateResult:
    passed: bool
    failure: FailureEntry | None = None


def evaluate_documentation_gate(
    worktree_path: Path | str,
    spec_dir: Path | str,
) -> DocumentationGateResult:
    """Validate TECH WRITER's documentation impact report and required docs."""
    worktree = Path(worktree_path)
    spec = Path(spec_dir)
    if not spec.is_absolute():
        spec = worktree / spec

    report = spec / REPORT_NAME
    if not report.exists():
        return _fail("documentation-impact-report-missing", f"missing {report}")

    metadata = _frontmatter(report)
    docs_required = metadata.get("docs_required")
    if docs_required is not True and docs_required is not False:
        return _fail(
            "documentation-impact-report-invalid",
            f"{report} must set docs_required true or false",
        )

    if docs_required is False:
        reason = str(metadata.get("not_applicable_reason") or "").strip()
        if not reason:
            return _fail(
                "documentation-not-applicable-without-reason",
                f"{report} must explain why docs are not applicable",
            )
        return DocumentationGateResult(passed=True)

    readme_updated = metadata.get("readme_updated") is True
    changelog_updated = metadata.get("changelog_updated") is True
    if not readme_updated or not changelog_updated:
        return _fail(
            "documentation-required-report-incomplete",
            f"{report} says docs are required but README/CHANGELOG updates are not both true",
        )

    readme = worktree / "README.md"
    changelog = worktree / "CHANGELOG.md"
    if not readme.exists() or not changelog.exists():
        return _fail(
            "documentation-required-files-missing",
            "docs are required but README.md or CHANGELOG.md is missing",
        )

    changed = _changed_paths(worktree)
    if "README.md" not in changed or "CHANGELOG.md" not in changed:
        return _fail(
            "documentation-required-without-doc-changes",
            "docs are required but README.md and CHANGELOG.md are not both changed at current HEAD",
        )

    if metadata.get("changelog_format") != "keep_a_changelog":
        return _fail(
            "changelog-format-not-declared",
            f"{report} must declare changelog_format: keep_a_changelog",
        )
    if not _looks_like_keep_a_changelog(changelog.read_text(encoding="utf-8")):
        return _fail(
            "changelog-format-invalid",
            "CHANGELOG.md must contain Keep a Changelog link, [Unreleased], and at least one category heading",
        )

    return DocumentationGateResult(passed=True)


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    data = yaml.safe_load(match.group(1)) or {}
    return data if isinstance(data, dict) else {}


def _changed_paths(worktree: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.add(path.strip('"'))
    return changed


def _looks_like_keep_a_changelog(text: str) -> bool:
    category_pattern = "|".join(re.escape(category) for category in CHANGELOG_CATEGORIES)
    return (
        "keepachangelog.com" in text.lower()
        and re.search(r"(?m)^## \[Unreleased\]", text) is not None
        and re.search(rf"(?m)^### ({category_pattern})", text) is not None
    )


def _fail(identifier: str, error: str) -> DocumentationGateResult:
    return DocumentationGateResult(
        passed=False,
        failure=FailureEntry(
            category=FailureCategory.OTHER,
            id=identifier,
            error=error,
        ),
    )
