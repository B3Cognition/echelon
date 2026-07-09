"""Deterministic README/CHANGELOG currency gate for harness builds."""

from __future__ import annotations

from dataclasses import dataclass
import json
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

    changelog_text = changelog.read_text(encoding="utf-8")
    if _has_planned_changelog_entry(changelog_text):
        return _fail(
            "changelog-planned-entry",
            "CHANGELOG.md [Unreleased] entries must describe actual changes, not planned roadmap work",
        )

    readme_failure = _readme_first_run_manual_failure(readme, worktree)
    if readme_failure:
        return _fail("readme-first-run-manual-incomplete", readme_failure)

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


def _has_planned_changelog_entry(text: str) -> bool:
    unreleased = _section_text(text, r"^## \[Unreleased\]")
    return re.search(
        r"(?im)^\s*[-*]\s*(planned|todo|future|coming soon)\b",
        unreleased,
    ) is not None


def _section_text(text: str, heading_pattern: str) -> str:
    match = re.search(rf"(?im){heading_pattern}.*$", text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_heading = re.search(r"(?m)^##\s+", rest)
    return rest[: next_heading.start()] if next_heading else rest


def _readme_first_run_manual_failure(readme: Path, worktree: Path) -> str:
    text = readme.read_text(encoding="utf-8")
    lowered = text.lower()
    missing: list[str] = []

    if not _has_terms(lowered, ("prerequisites", "requirements")):
        missing.append("Prerequisites")
    if _package_requires_node(worktree) and "node" not in lowered:
        missing.append("Node.js prerequisite from package.json")
    if "install" not in lowered:
        missing.append("install instructions")
    if not _has_terms(lowered, ("configuration", "config")):
        missing.append("configuration")
    if not _has_minimal_working_input(text):
        missing.append("minimal working input")
    if not ("dry-run" in lowered or "dry run" in lowered):
        missing.append("first dry run")
    if not _has_expected_dry_run_output(lowered):
        missing.append("expected dry-run output")
    if not _has_terms(lowered, ("apply", "run", "start")):
        missing.append("first real run")
    if not _has_terms(lowered, ("expected files", "generated files", "service url")):
        missing.append("expected files or generated output")
    if "troubleshooting" not in lowered:
        missing.append("troubleshooting")
    if not _has_terms(lowered, ("develop", "development")):
        missing.append("development commands")

    if not missing:
        return ""
    return "README.md is not a first-run manual; missing: " + ", ".join(missing)


def _has_terms(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _package_requires_node(worktree: Path) -> bool:
    package = worktree / "package.json"
    if not package.exists():
        return False
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if isinstance(data, dict):
        engines = data.get("engines")
        if isinstance(engines, dict) and engines.get("node"):
            return True
        if data.get("bin"):
            return True
    return False


def _has_minimal_working_input(text: str) -> bool:
    if re.search(
        r"(?im)create\s+`[^`]*(rules|commands|skills|subagents)[^`]*\.md`",
        text,
    ):
        return True
    return re.search(r"(?im)mkdir\s+-p\s+[^`\n]*(rules|commands|skills|subagents)", text) is not None


def _has_expected_dry_run_output(text: str) -> bool:
    if "expected output" not in text:
        return False
    return "dry-run" in text or "dry run" in text


def _fail(identifier: str, error: str) -> DocumentationGateResult:
    return DocumentationGateResult(
        passed=False,
        failure=FailureEntry(
            category=FailureCategory.OTHER,
            id=identifier,
            error=error,
        ),
    )
