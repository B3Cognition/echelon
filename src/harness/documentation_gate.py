"""Deterministic README/CHANGELOG currency gate for harness builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Iterable

import yaml

from harness.docs_verifier import (
    DOCS_VERIFICATION_REPORT_NAME,
    REPORT_NAME,
    verify_docs,
)
from harness.verify_result import FailureCategory, FailureEntry


@dataclass(frozen=True)
class DocumentationGateResult:
    passed: bool
    failure: FailureEntry | None = None


def evaluate_documentation_gate(
    worktree_path: Path | str,
    spec_dir: Path | str,
    *,
    changed_files: Iterable[str] | None = None,
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

    changed = (
        _normalize_changed_paths(changed_files)
        if changed_files is not None
        else _changed_paths(worktree)
    )
    if "README.md" not in changed or "CHANGELOG.md" not in changed:
        return _fail(
            "documentation-required-without-doc-changes",
            "docs are required but README.md and CHANGELOG.md are not both changed in the delivery slice",
        )

    deterministic_failure = _deterministic_docs_failure(worktree, spec, metadata)
    if deterministic_failure:
        identifier, error = deterministic_failure
        return _fail(identifier, error)

    docs_verification_failure = _docs_verification_report_failure(spec)
    if docs_verification_failure:
        identifier, error = docs_verification_failure
        return _fail(identifier, error)

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
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        paths.append(line[3:].strip())
    return _normalize_changed_paths(paths)


def _normalize_changed_paths(paths: Iterable[str]) -> set[str]:
    changed: set[str] = set()
    for raw_path in paths:
        path = str(raw_path).strip()
        if not path:
            continue
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.add(path.strip('"'))
    return changed


def _deterministic_docs_failure(
    worktree: Path,
    spec: Path,
    metadata: dict,
) -> tuple[str, str] | None:
    if metadata.get("changelog_format") != "keep_a_changelog":
        return (
            "changelog-format-not-declared",
            f"{spec / REPORT_NAME} must declare changelog_format: keep_a_changelog",
        )

    result = verify_docs(worktree, spec)
    if not result.findings:
        return None

    finding = result.findings[0]
    if finding.document == "README.md" and finding.section == "Command Claims":
        return ("readme-command-claim-unsupported", finding.evidence)
    if finding.document == "README.md":
        return ("readme-first-run-manual-incomplete", finding.issue)
    if finding.document == "CHANGELOG.md" and "planned" in finding.issue.lower():
        return (
            "changelog-planned-entry",
            "CHANGELOG.md [Unreleased] entries must describe actual changes, not planned roadmap work",
        )
    if finding.document == "CHANGELOG.md":
        return (
            "changelog-format-invalid",
            "CHANGELOG.md must contain Keep a Changelog link, [Unreleased], and at least one category heading",
        )
    return ("documentation-impact-report-invalid", finding.issue)


def _docs_verification_report_failure(spec_dir: Path) -> tuple[str, str] | None:
    report = spec_dir / DOCS_VERIFICATION_REPORT_NAME
    if not report.exists():
        return (
            "docs-verification-report-missing",
            f"missing {report}",
        )

    metadata = _frontmatter(report)
    if not metadata:
        return (
            "docs-verification-report-invalid",
            f"{report} must include machine-readable YAML frontmatter",
        )

    verdict = str(metadata.get("verdict") or "").strip().upper()
    if verdict != "PASS":
        return (
            "docs-verification-report-failed",
            f"{report} must declare verdict: PASS before finalization",
        )

    required_true = (
        "readme_first_run_manual",
        "changelog_valid",
        "impact_report_valid",
        "project_evidence_checked",
    )
    missing_true = [key for key in required_true if metadata.get(key) is not True]
    if missing_true:
        return (
            "docs-verification-report-invalid",
            f"{report} must set {', '.join(missing_true)} to true",
        )

    try:
        blocking_findings = int(metadata.get("blocking_findings"))
    except (TypeError, ValueError):
        return (
            "docs-verification-report-invalid",
            f"{report} must set blocking_findings to 0",
        )
    if blocking_findings != 0:
        return (
            "docs-verification-report-failed",
            f"{report} has {blocking_findings} blocking documentation finding(s)",
        )

    try:
        evidence_items_checked = int(metadata.get("evidence_items_checked"))
    except (TypeError, ValueError):
        return (
            "docs-verification-report-invalid",
            f"{report} must set evidence_items_checked to at least 4",
        )
    if evidence_items_checked < 4:
        return (
            "docs-verification-report-invalid",
            f"{report} must check README, CHANGELOG, impact report, and project evidence",
        )

    return None


def _fail(identifier: str, error: str) -> DocumentationGateResult:
    return DocumentationGateResult(
        passed=False,
        failure=FailureEntry(
            category=FailureCategory.OTHER,
            id=identifier,
            error=error,
        ),
    )
