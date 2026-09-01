"""Deterministic README/CHANGELOG verifier for TECH WRITER convergence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Mapping

import yaml

from harness.runnability_evidence import (
    RunnabilityEvidenceRef,
    validate_runnability_report,
)


REPORT_NAME = "documentation-impact-report.md"
DOCS_VERIFICATION_REPORT_NAME = "docs-verification-report.md"
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
class DocsFinding:
    identifier: str
    severity: str
    document: str
    section: str
    issue: str
    evidence: str
    required_repair: str


@dataclass(frozen=True)
class DocsVerificationResult:
    verdict: str
    report_path: Path
    readme_first_run_manual: bool
    changelog_valid: bool
    impact_report_valid: bool
    project_evidence_checked: bool
    evidence_items_checked: int
    evidence_items: tuple[str, ...]
    blocking_findings: int
    findings: tuple[DocsFinding, ...]
    reviewed_change_ids: tuple[str, ...]
    uncovered_change_ids: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    runnability_evidence_sha256: str = ""
    runnability_commands_current: bool = False


def write_docs_verification_report(
    worktree_path: Path | str,
    spec_dir: Path | str,
    *,
    runnability_report: RunnabilityEvidenceRef | None = None,
) -> DocsVerificationResult:
    """Evaluate docs and write the machine-readable docs verification report."""
    worktree = Path(worktree_path)
    spec = Path(spec_dir)
    if not spec.is_absolute():
        spec = worktree / spec

    result = verify_docs(worktree, spec, runnability_report=runnability_report)
    result.report_path.parent.mkdir(parents=True, exist_ok=True)
    result.report_path.write_text(_report_markdown(result), encoding="utf-8")
    return result


def verify_docs(
    worktree_path: Path | str,
    spec_dir: Path | str,
    *,
    runnability_report: RunnabilityEvidenceRef | None = None,
) -> DocsVerificationResult:
    """Evaluate TECH WRITER documentation artifacts deterministically."""
    worktree = Path(worktree_path)
    spec = Path(spec_dir)
    if not spec.is_absolute():
        spec = worktree / spec

    report_path = spec / DOCS_VERIFICATION_REPORT_NAME
    evidence = _evidence_items(worktree, spec)
    findings: list[DocsFinding] = []
    runnability_payload, runnability_failure = _current_runnability_payload(
        runnability_report
    )
    runnability_commands_current = runnability_payload is not None
    runnability_evidence_sha256 = (
        runnability_report.evidence_sha256 if runnability_commands_current else ""
    )
    if runnability_failure:
        findings.append(
            _finding(
                _next_id(findings),
                "docs-verification-report.md",
                "User Runnability Evidence",
                runnability_failure,
                str(runnability_report.path) if runnability_report else "missing report",
                "Rerun the user-runnability gate and regenerate documentation evidence.",
            )
        )

    impact_report = spec / REPORT_NAME
    metadata: dict = {}
    impact_report_valid = True
    if not impact_report.exists():
        impact_report_valid = False
        findings.append(
            _finding(
                "DOCS-001",
                "documentation-impact-report.md",
                "Impact Report",
                f"missing {impact_report}",
                "file not found",
                "Write documentation-impact-report.md with the TECH WRITER frontmatter.",
            )
        )
    else:
        metadata = _frontmatter(impact_report)
        impact_report_valid = _impact_report_valid(metadata)
        if not impact_report_valid:
            findings.append(
                _finding(
                    "DOCS-001",
                    "documentation-impact-report.md",
                    "Impact Report",
                    "frontmatter is missing required documentation decision fields",
                    "required keys: docs_required, readme_updated, changelog_updated, changelog_format",
                    "Repair the report frontmatter so Ralph can audit the docs decision.",
                )
            )

    docs_required = metadata.get("docs_required") is True
    reviewed_change_ids: list[str] = []
    uncovered_change_ids: list[str] = []
    unsupported_claims: list[str] = []
    if metadata.get("schema_version") == 2:
        reviewed_change_ids = _string_list(metadata.get("delivery_change_ids"))
        raw_entries = metadata.get("documented_changes")
        entries = raw_entries if isinstance(raw_entries, list) else []
        entry_ids = {
            str(entry.get("change_id") or "").strip()
            for entry in entries
            if isinstance(entry, dict)
        }
        uncovered_change_ids = sorted(set(reviewed_change_ids) - entry_ids)
        for change_id in uncovered_change_ids:
            findings.append(
                _finding(
                    _next_id(findings),
                    "documentation-impact-report.md",
                    "Coverage Map",
                    f"{change_id} has no documentation coverage disposition",
                    "delivery_change_ids and documented_changes differ",
                    f"Add a source-backed documented_changes entry for {change_id}.",
                )
            )
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("disposition") != "covered":
                continue
            change_id = str(entry.get("change_id") or "").strip()
            for raw_path in _string_list(entry.get("evidence_paths")):
                candidate = (worktree.resolve() / raw_path).resolve()
                if not candidate.is_relative_to(worktree.resolve()) or not candidate.exists():
                    claim = f"{change_id} cites invalid evidence path {raw_path}"
                    unsupported_claims.append(claim)
                    findings.append(
                        _finding(
                            _next_id(findings),
                            "documentation-impact-report.md",
                            "Evidence",
                            claim,
                            raw_path,
                            "Cite an existing in-repository source, test, or runtime evidence path.",
                        )
                    )
    if not docs_required:
        reason = str(metadata.get("not_applicable_reason") or "").strip()
        if (
            metadata.get("docs_required") is False
            and reason
            and runnability_payload is None
        ):
            return _result(
                report_path=report_path,
                readme_first_run_manual=True,
                changelog_valid=True,
                impact_report_valid=impact_report_valid,
                evidence_items_checked=evidence,
                findings=findings,
                reviewed_change_ids=reviewed_change_ids,
                uncovered_change_ids=uncovered_change_ids,
                unsupported_claims=unsupported_claims,
                runnability_evidence_sha256=runnability_evidence_sha256,
                runnability_commands_current=runnability_commands_current,
            )

    if len(evidence) < 4:
        findings.append(
            _finding(
                _next_id(findings),
                "docs-verification-report.md",
                "Project Evidence",
                "documentation verification did not inspect project evidence",
                "checked only README.md, CHANGELOG.md, and documentation-impact-report.md",
                "Inspect package metadata, scripts, CLI/config source, tests, changed files, or safe smoke evidence before passing docs.",
            )
        )

    readme = worktree / "README.md"
    changelog = worktree / "CHANGELOG.md"
    readme_first_run_manual = True
    changelog_valid = True

    if not readme.exists():
        readme_first_run_manual = False
        findings.append(
            _finding(
                _next_id(findings),
                "README.md",
                "First Run",
                "README.md is missing",
                "file not found",
                "Create a first-run README manual.",
            )
        )
    else:
        readme_failure = readme_first_run_manual_failure(readme, worktree)
        unsupported_commands = unsupported_readme_npm_script_commands(readme, worktree)
        if readme_failure:
            readme_first_run_manual = False
            findings.append(
                _finding(
                    _next_id(findings),
                    "README.md",
                    "First Run",
                    readme_failure,
                    "README.md content",
                    "Add the missing first-run manual sections using project evidence.",
                )
            )
        if unsupported_commands:
            readme_first_run_manual = False
            findings.append(
                _finding(
                    _next_id(findings),
                    "README.md",
                    "Command Claims",
                    "README.md references npm script command(s) not declared in package.json",
                    ", ".join(unsupported_commands),
                    "Remove unsupported npm commands or add the scripts to package.json.",
                )
            )
        if runnability_payload is not None:
            missing_claims = _missing_runnability_readme_claims(
                readme.read_text(encoding="utf-8"),
                runnability_payload.get("user_commands"),
            )
            for section, command in missing_claims:
                readme_first_run_manual = False
                findings.append(
                    _finding(
                        _next_id(findings),
                        "README.md",
                        "Observed First Run",
                        f"README.md omits the observed {section} instruction",
                        command,
                        f"Document the exact observed {section} instruction: {command}",
                    )
                )

    if not changelog.exists():
        changelog_valid = False
        findings.append(
            _finding(
                _next_id(findings),
                "CHANGELOG.md",
                "Unreleased",
                "CHANGELOG.md is missing",
                "file not found",
                "Create CHANGELOG.md with a Keep a Changelog-style [Unreleased] entry.",
            )
        )
    else:
        changelog_text = changelog.read_text(encoding="utf-8")
        if not looks_like_keep_a_changelog(changelog_text):
            changelog_valid = False
            findings.append(
                _finding(
                    _next_id(findings),
                    "CHANGELOG.md",
                    "Unreleased",
                    "CHANGELOG.md does not follow the required Keep a Changelog shape",
                    "missing Keep a Changelog link, [Unreleased], or category heading",
                    "Use [Unreleased] with a completed-change category such as Added or Fixed.",
                )
            )
        if has_planned_changelog_entry(changelog_text):
            changelog_valid = False
            findings.append(
                _finding(
                    _next_id(findings),
                    "CHANGELOG.md",
                    "Unreleased",
                    "CHANGELOG.md includes planned roadmap work",
                    "planned/todo/future/coming soon entry under [Unreleased]",
                    "Replace roadmap text with actual completed user-facing changes.",
                )
            )

    return _result(
        report_path=report_path,
        readme_first_run_manual=readme_first_run_manual,
        changelog_valid=changelog_valid,
        impact_report_valid=impact_report_valid,
        evidence_items_checked=evidence,
        findings=findings,
        reviewed_change_ids=reviewed_change_ids,
        uncovered_change_ids=uncovered_change_ids,
        unsupported_claims=unsupported_claims,
        runnability_evidence_sha256=runnability_evidence_sha256,
        runnability_commands_current=runnability_commands_current,
    )


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    data = yaml.safe_load(match.group(1)) or {}
    return data if isinstance(data, dict) else {}


def looks_like_keep_a_changelog(text: str) -> bool:
    category_pattern = "|".join(re.escape(category) for category in CHANGELOG_CATEGORIES)
    return (
        "keepachangelog.com" in text.lower()
        and re.search(r"(?m)^## \[Unreleased\]", text) is not None
        and re.search(rf"(?m)^### ({category_pattern})", text) is not None
    )


def has_planned_changelog_entry(text: str) -> bool:
    unreleased = section_text(text, r"^## \[Unreleased\]")
    return re.search(
        r"(?im)^\s*[-*]\s*(planned|todo|future|coming soon)\b",
        unreleased,
    ) is not None


def readme_first_run_manual_failure(readme: Path, worktree: Path) -> str:
    text = readme.read_text(encoding="utf-8")
    lowered = text.lower()
    missing: list[str] = []

    if not _has_terms(lowered, ("prerequisites", "requirements")):
        missing.append("Prerequisites")
    if package_requires_node(worktree) and "node" not in lowered:
        missing.append("Node.js prerequisite from package.json")
    if "install" not in lowered:
        missing.append("install instructions")
    if not _has_terms(lowered, ("configuration", "config")):
        missing.append("configuration")
    if not has_minimal_working_input(text):
        missing.append("minimal working input")
    if not ("dry-run" in lowered or "dry run" in lowered):
        missing.append("first dry run")
    if not has_expected_dry_run_output(lowered):
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


def unsupported_readme_npm_script_commands(readme: Path, worktree: Path) -> list[str]:
    package = package_json(worktree / "package.json")
    if not isinstance(package, dict):
        return []

    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        scripts = {}
    declared = {key for key in scripts if isinstance(key, str)}
    text = readme.read_text(encoding="utf-8")
    unsupported: list[str] = []
    seen: set[str] = set()

    for match in re.finditer(
        r"\bnpm\s+(?:run\s+([A-Za-z0-9:_-]+)|(test|start|stop|restart)\b)",
        text,
    ):
        script = match.group(1) or match.group(2)
        command = f"npm run {script}" if match.group(1) else f"npm {script}"
        if script not in declared and command not in seen:
            unsupported.append(command)
            seen.add(command)

    return unsupported


def package_requires_node(worktree: Path) -> bool:
    package = package_json(worktree / "package.json")
    if isinstance(package, dict):
        engines = package.get("engines")
        if isinstance(engines, dict) and engines.get("node"):
            return True
        if package.get("bin"):
            return True
    return False


def package_json(package: Path) -> object:
    if not package.exists():
        return None
    try:
        return json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def section_text(text: str, heading_pattern: str) -> str:
    match = re.search(rf"(?im){heading_pattern}.*$", text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_heading = re.search(r"(?m)^##\s+", rest)
    return rest[: next_heading.start()] if next_heading else rest


def has_minimal_working_input(text: str) -> bool:
    if re.search(
        r"(?im)create\s+`[^`]*(rules|commands|skills|subagents)[^`]*\.md`",
        text,
    ):
        return True
    return re.search(r"(?im)mkdir\s+-p\s+[^`\n]*(rules|commands|skills|subagents)", text) is not None


def has_expected_dry_run_output(text: str) -> bool:
    if "expected output" not in text:
        return False
    return "dry-run" in text or "dry run" in text


def _frontmatter(path: Path) -> dict:
    return frontmatter(path)


def _impact_report_valid(metadata: dict) -> bool:
    docs_required = metadata.get("docs_required")
    if docs_required is not True and docs_required is not False:
        return False
    if docs_required is False:
        return bool(str(metadata.get("not_applicable_reason") or "").strip())
    return (
        metadata.get("readme_updated") is True
        and metadata.get("changelog_updated") is True
        and metadata.get("changelog_format") == "keep_a_changelog"
    )


def _evidence_items(worktree: Path, spec_dir: Path) -> list[str]:
    items = [
        "README.md",
        "CHANGELOG.md",
        f"{spec_dir.name}/{REPORT_NAME}",
    ]
    for candidate in (
        "package.json",
        "pyproject.toml",
        "setup.py",
        "Cargo.toml",
        "go.mod",
    ):
        if (worktree / candidate).exists():
            items.append(candidate)
    changed = _changed_paths(worktree)
    if changed:
        items.append("git changed-file list")
    return items


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


def _result(
    *,
    report_path: Path,
    readme_first_run_manual: bool,
    changelog_valid: bool,
    impact_report_valid: bool,
    evidence_items_checked: list[str],
    findings: list[DocsFinding],
    reviewed_change_ids: list[str],
    uncovered_change_ids: list[str],
    unsupported_claims: list[str],
    runnability_evidence_sha256: str = "",
    runnability_commands_current: bool = False,
) -> DocsVerificationResult:
    blocking = sum(1 for finding in findings if finding.severity == "blocking")
    verdict = "PASS" if blocking == 0 else "FAIL"
    return DocsVerificationResult(
        verdict=verdict,
        report_path=report_path,
        readme_first_run_manual=readme_first_run_manual,
        changelog_valid=changelog_valid,
        impact_report_valid=impact_report_valid,
        project_evidence_checked=len(evidence_items_checked) >= 4,
        evidence_items_checked=len(evidence_items_checked),
        evidence_items=tuple(evidence_items_checked),
        blocking_findings=blocking,
        findings=tuple(findings),
        reviewed_change_ids=tuple(reviewed_change_ids),
        uncovered_change_ids=tuple(uncovered_change_ids),
        unsupported_claims=tuple(unsupported_claims),
        runnability_evidence_sha256=runnability_evidence_sha256,
        runnability_commands_current=runnability_commands_current,
    )


def _finding(
    identifier: str,
    document: str,
    section: str,
    issue: str,
    evidence: str,
    required_repair: str,
) -> DocsFinding:
    return DocsFinding(
        identifier=identifier,
        severity="blocking",
        document=document,
        section=section,
        issue=issue,
        evidence=evidence,
        required_repair=required_repair,
    )


def _next_id(findings: list[DocsFinding]) -> str:
    return f"DOCS-{len(findings) + 1:03d}"


def _report_markdown(result: DocsVerificationResult) -> str:
    metadata = {
        "schema_version": 2,
        "reviewed_change_ids": list(result.reviewed_change_ids),
        "uncovered_change_ids": list(result.uncovered_change_ids),
        "unsupported_claims": list(result.unsupported_claims),
        "verdict": result.verdict,
        "readme_first_run_manual": result.readme_first_run_manual,
        "changelog_valid": result.changelog_valid,
        "impact_report_valid": result.impact_report_valid,
        "project_evidence_checked": result.project_evidence_checked,
        "evidence_items_checked": result.evidence_items_checked,
        "blocking_findings": result.blocking_findings,
        "runnability_evidence_sha256": result.runnability_evidence_sha256,
        "runnability_commands_current": result.runnability_commands_current,
    }
    rows = [
        "| ID | Severity | Document | Section | Issue | Evidence | Required Repair |",
        "|----|----------|----------|---------|-------|----------|-----------------|",
    ]
    if result.findings:
        rows.extend(
            "| {id} | {severity} | {document} | {section} | {issue} | {evidence} | {repair} |".format(
                id=_escape_table(finding.identifier),
                severity=_escape_table(finding.severity),
                document=_escape_table(finding.document),
                section=_escape_table(finding.section),
                issue=_escape_table(finding.issue),
                evidence=_escape_table(finding.evidence),
                repair=_escape_table(finding.required_repair),
            )
            for finding in result.findings
        )
    else:
        rows.append("| (none) | (none) | (none) | (none) | (none) | deterministic verifier | (none) |")

    return (
        "---\n"
        f"{yaml.safe_dump(metadata, sort_keys=False)}"
        "---\n\n"
        "# Docs Verification Report\n\n"
        "## Verdict\n\n"
        f"{result.verdict}\n\n"
        "## Evidence Checked\n\n"
        + "\n".join(f"- {item}" for item in result.evidence_items)
        + "\n\n"
        "## Findings\n\n"
        + "\n".join(rows)
        + "\n"
    )


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _has_terms(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _current_runnability_payload(
    report: RunnabilityEvidenceRef | None,
) -> tuple[dict[str, object] | None, str]:
    if report is None:
        return None, ""
    validation = validate_runnability_report(
        report,
        candidate_commit=report.candidate_commit,
        candidate_fingerprint=report.candidate_fingerprint,
        contract_hash=report.contract_hash,
        stack_hash=report.stack_hash,
    )
    if not validation.valid:
        return None, f"user-runnability evidence is not current: {validation.reason}"
    try:
        payload = json.loads(report.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "user-runnability evidence is unavailable or malformed"
    if not isinstance(payload, dict):
        return None, "user-runnability evidence is not an object"
    return payload, ""


def _missing_runnability_readme_claims(
    readme_text: str,
    raw_commands: object,
) -> list[tuple[str, str]]:
    if not isinstance(raw_commands, Mapping):
        return []
    normalized_readme = _normalize_command_claim(readme_text)
    missing: list[tuple[str, str]] = []
    for section in (
        "prerequisites",
        "install",
        "provision",
        "bootstrap",
        "start",
        "open",
        "stop",
    ):
        values = raw_commands.get(section)
        if not isinstance(values, list):
            continue
        for value in values:
            command = str(value).strip()
            if command and _normalize_command_claim(command) not in normalized_readme:
                missing.append((section, command))
    return missing


def _normalize_command_claim(value: str) -> str:
    return " ".join(value.split())
