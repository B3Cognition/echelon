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
from harness.runnability_evidence import RunnabilityEvidenceRef
from harness.verify_result import FailureCategory, FailureEntry


DOCUMENTATION_COVERAGE_FAILURE_BATCH_LIMIT = 5


@dataclass(frozen=True)
class DocumentationGateResult:
    passed: bool
    failure: FailureEntry | None = None


def write_not_applicable_documentation_impact_report(
    spec_dir: Path | str,
    *,
    reason: str,
) -> Path:
    """Write Ralph-owned no-impact docs report for a no-op delivery slice."""
    spec = Path(spec_dir)
    spec.mkdir(parents=True, exist_ok=True)
    report = spec / REPORT_NAME
    metadata = {
        "docs_required": False,
        "readme_updated": False,
        "changelog_updated": False,
        "changelog_format": "not_required",
        "not_applicable_reason": reason,
    }
    report.write_text(
        "---\n"
        f"{yaml.safe_dump(metadata, sort_keys=False)}"
        "---\n"
        "# Documentation Impact Report\n\n"
        "Ralph generated this report because the delivery slice made no target "
        "source or documentation changes and only needed harness-owned "
        "verification bookkeeping.\n",
        encoding="utf-8",
    )
    return report


def evaluate_documentation_gate(
    worktree_path: Path | str,
    spec_dir: Path | str,
    *,
    changed_files: Iterable[str] | None = None,
    runnability_report: RunnabilityEvidenceRef | None = None,
    runnability_required: bool = False,
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
            f"{report} must set exactly `docs_required: true` or "
            "`docs_required: false` in YAML frontmatter",
        )

    if runnability_required and runnability_report is None:
        return _fail(
            "docs-runnability-evidence-missing",
            "final documentation convergence requires current passing user-runnability evidence",
        )

    if runnability_report is not None:
        runnability_docs = verify_docs(
            worktree,
            spec,
            runnability_report=runnability_report,
        )
        runnability_findings = [
            finding
            for finding in runnability_docs.findings
            if finding.section in {"Observed First Run", "User Runnability Evidence"}
        ]
        if runnability_findings:
            finding = runnability_findings[0]
            return _fail("docs-runnability-commands-stale", finding.issue)

    if docs_required is False:
        reason = str(metadata.get("not_applicable_reason") or "").strip()
        if not reason:
            return _fail(
                "documentation-not-applicable-without-reason",
                f"{report} must set a non-empty YAML frontmatter field "
                "`not_applicable_reason`. Narrative prose and aliases such as "
                "`reason` do not satisfy the report schema.",
            )
        return DocumentationGateResult(passed=True)

    readme_updated = metadata.get("readme_updated") is True
    changelog_updated = metadata.get("changelog_updated") is True
    if not readme_updated or not changelog_updated:
        return _fail(
            "documentation-required-report-incomplete",
            f"{report} sets `docs_required: true`, so YAML frontmatter must also "
            "set both `readme_updated: true` and `changelog_updated: true`",
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

    deterministic_failure = _deterministic_docs_failure(
        worktree,
        spec,
        metadata,
        runnability_report=runnability_report,
    )
    if deterministic_failure:
        identifier, error = deterministic_failure
        return _fail(identifier, error)

    docs_verification_failure = _docs_verification_report_failure(
        spec,
        runnability_required=runnability_required,
        expected_runnability_sha256=(
            runnability_report.evidence_sha256 if runnability_report else ""
        ),
    )
    if docs_verification_failure:
        identifier, error = docs_verification_failure
        return _fail(identifier, error)

    if metadata.get("schema_version") == 2:
        verification_metadata = _frontmatter(spec / DOCS_VERIFICATION_REPORT_NAME)
        coverage_failure = validate_documentation_coverage(
            worktree,
            metadata,
            verification_metadata,
        )
        if coverage_failure:
            identifier, error = coverage_failure
            return _fail(identifier, error)

    return DocumentationGateResult(passed=True)


def validate_documentation_coverage(
    worktree: Path | str,
    impact_metadata: dict,
    verification_metadata: dict,
) -> tuple[str, str] | None:
    """Validate the version-2 change-to-documentation evidence contract."""
    if impact_metadata.get("schema_version") != 2:
        return None

    delivery_ids = _nonempty_string_list(impact_metadata.get("delivery_change_ids"))
    if not delivery_ids:
        return (
            "documentation-coverage-incomplete",
            "schema version 2 requires non-empty delivery_change_ids",
        )
    if len(delivery_ids) != len(set(delivery_ids)):
        return (
            "documentation-coverage-incomplete",
            "delivery_change_ids must be unique",
        )

    raw_entries = impact_metadata.get("documented_changes")
    entries = raw_entries if isinstance(raw_entries, list) else []
    by_id: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return (
                "documentation-coverage-incomplete",
                "every documented_changes entry must be a mapping",
            )
        change_id = str(entry.get("change_id") or "").strip()
        if not change_id or change_id in by_id:
            return (
                "documentation-coverage-incomplete",
                "documented change IDs must be non-empty and unique",
            )
        by_id[change_id] = entry

    missing = sorted(set(delivery_ids) - set(by_id))
    extra = sorted(set(by_id) - set(delivery_ids))
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("missing dispositions: " + ", ".join(missing))
        if extra:
            details.append("unknown change IDs: " + ", ".join(extra))
        return ("documentation-coverage-incomplete", "; ".join(details))

    root = Path(worktree).resolve()
    coverage_errors: list[str] = []
    for change_id in delivery_ids:
        entry = by_id[change_id]
        disposition = str(entry.get("disposition") or "").strip()
        if disposition not in {"covered", "not_applicable"}:
            coverage_errors.append(
                f"{change_id} must use disposition covered or not_applicable"
            )
            continue
        if disposition == "not_applicable":
            if not str(entry.get("reason") or "").strip():
                coverage_errors.append(
                    f"{change_id} not_applicable disposition requires a reason",
                )
            continue
        if not _nonempty_string_list(entry.get("readme_sections")):
            coverage_errors.append(
                f"{change_id} must cite at least one README section",
            )
        if not _nonempty_string_list(entry.get("changelog_sections")):
            coverage_errors.append(
                f"{change_id} must cite at least one CHANGELOG section",
            )

    if coverage_errors:
        return (
            "documentation-coverage-incomplete",
            _format_batched_documentation_coverage_errors(coverage_errors),
        )

    for change_id in delivery_ids:
        entry = by_id[change_id]
        if str(entry.get("disposition") or "").strip() == "not_applicable":
            continue
        evidence_paths = _nonempty_string_list(entry.get("evidence_paths"))
        if not evidence_paths:
            return (
                "documentation-evidence-invalid",
                f"{change_id} must cite at least one implementation evidence path",
            )
        for raw_path in evidence_paths:
            evidence_path = (root / raw_path).resolve()
            if not evidence_path.is_relative_to(root) or not evidence_path.exists():
                return (
                    "documentation-evidence-invalid",
                    f"{change_id} cites missing or out-of-repository evidence path: {raw_path}",
                )

    reviewed = set(_nonempty_string_list(verification_metadata.get("reviewed_change_ids")))
    if reviewed != set(delivery_ids):
        unreviewed = sorted(set(delivery_ids) - reviewed)
        return (
            "documentation-coverage-incomplete",
            "DOCS VERIFIER did not review: " + ", ".join(unreviewed or delivery_ids),
        )
    uncovered = _nonempty_string_list(verification_metadata.get("uncovered_change_ids"))
    if uncovered:
        return (
            "documentation-coverage-incomplete",
            "DOCS VERIFIER found uncovered changes: " + ", ".join(uncovered),
        )
    unsupported = _nonempty_string_list(verification_metadata.get("unsupported_claims"))
    if unsupported:
        return (
            "documentation-claim-unsupported",
            "DOCS VERIFIER found unsupported claims: " + "; ".join(unsupported),
        )
    return None


def _format_batched_documentation_coverage_errors(errors: list[str]) -> str:
    shown = errors[:DOCUMENTATION_COVERAGE_FAILURE_BATCH_LIMIT]
    remaining = len(errors) - len(shown)
    message = "; ".join(shown)
    if remaining:
        noun = "issue" if remaining == 1 else "issues"
        message += f"; and {remaining} more documentation coverage {noun}"
    return message


def _nonempty_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
    *,
    runnability_report: RunnabilityEvidenceRef | None = None,
) -> tuple[str, str] | None:
    if metadata.get("changelog_format") != "keep_a_changelog":
        return (
            "changelog-format-not-declared",
            f"{spec / REPORT_NAME} must declare changelog_format: keep_a_changelog",
        )

    result = verify_docs(
        worktree,
        spec,
        runnability_report=runnability_report,
    )
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


def _docs_verification_report_failure(
    spec_dir: Path,
    *,
    runnability_required: bool = False,
    expected_runnability_sha256: str = "",
) -> tuple[str, str] | None:
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

    if runnability_required:
        if metadata.get("runnability_commands_current") is not True:
            return (
                "docs-runnability-evidence-stale",
                f"{report} is provisional; regenerate it from current passing runnability evidence",
            )
        observed_sha = str(metadata.get("runnability_evidence_sha256") or "")
        if not expected_runnability_sha256 or observed_sha != expected_runnability_sha256:
            return (
                "docs-runnability-evidence-stale",
                f"{report} does not cite the current user-runnability evidence digest",
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
