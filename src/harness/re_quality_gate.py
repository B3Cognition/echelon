"""Deterministic deep-spec quality validation for staged RE output."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.re_domain_manifest import (
    ReDomain,
    domain_manifest_path,
    load_domain_manifest,
    source_files,
)
from harness.re_planner import ReExecutionPlan, RePlanSource
from harness.re_quality_contract import QUALITY_CONTRACT_VERSION
from harness.re_semantic_contract import (
    ReSemanticFindingRecord,
    classify_semantic_finding,
    stable_finding_id,
)
from harness.re_semantic_preflight import (
    SemanticPreflightFinding,
    check_semantic_preflight,
)
from harness.re_source_evidence import (
    SOURCE_REFERENCE,
    contains_source_reference,
    source_reference_matches,
    source_reference_ranges,
)


DEEP_SPEC_SECTIONS = (
    "User Scenarios & Testing",
    "Requirements (Functional)",
    "Requirements (Non-Functional)",
    "Key Entities",
    "Edge Cases",
)
MINIMUM_SOURCE_EVIDENCE = 5
SEMANTIC_QUALITY_REVIEW_VERSION = 1
_FILES_PER_COMPLEXITY_UNIT = 12
_LINES_PER_COMPLEXITY_UNIT = 800
_MAX_SCENARIOS = 12
_MAX_FUNCTIONAL_REQUIREMENTS = 20
_MAX_NON_FUNCTIONAL_REQUIREMENTS = 8
_SECTION_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)
_SUBSECTION_HEADING = re.compile(r"^###\s+(?P<title>.+?)\s*$", re.MULTILINE)
_SCENARIO_HEADING = re.compile(r"^(?:US-\d|Scenario\b|User Story\b|Use Case\b)", re.IGNORECASE)
_FUNCTIONAL_REQUIREMENT_HEADING = re.compile(
    r"^(?:FR-\d|Req(?:uirement)?\b)", re.IGNORECASE
)
_NON_FUNCTIONAL_REQUIREMENT_HEADING = re.compile(
    r"^(?:NFR-\d|Non-Functional Requirement\b)", re.IGNORECASE
)


@dataclass(frozen=True)
class ReSpecQualityFailure:
    source_id: str
    spec_path: Path
    missing_sections: tuple[str, ...]
    source_evidence_count: int
    domain_id: str | None = None
    reason: str = "deep_spec_incomplete"
    invalid_source_evidence: tuple[str, ...] = ()
    expected_scenario_count: int = 0
    scenario_count: int = 0
    scenarios_without_acceptance: tuple[str, ...] = ()
    scenarios_without_evidence: tuple[str, ...] = ()
    expected_functional_requirement_count: int = 0
    functional_requirement_count: int = 0
    functional_requirements_without_evidence: tuple[str, ...] = ()
    expected_non_functional_requirement_count: int = 0
    non_functional_requirement_count: int = 0
    non_functional_requirements_without_evidence: tuple[str, ...] = ()
    semantic_findings: tuple[str, ...] = ()
    semantic_finding_records: tuple[ReSemanticFindingRecord, ...] = ()
    semantic_preflight_findings: tuple[SemanticPreflightFinding, ...] = ()


@dataclass(frozen=True)
class ReQualityReport:
    passed: bool
    failures: tuple[ReSpecQualityFailure, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "quality_contract_version": QUALITY_CONTRACT_VERSION,
            "passed": self.passed,
            "failures": [
                {
                    **asdict(failure),
                    "spec_path": str(failure.spec_path),
                }
                for failure in self.failures
            ],
        }


@dataclass(frozen=True)
class ReSourceQualityReport:
    """Deterministic coverage and deep-spec status for one refreshed source."""

    source_id: str
    eligible_file_count: int
    covered_file_count: int
    coverage_pct: float
    coverage_threshold: int
    orphan_paths: tuple[str, ...]
    domain_failures: tuple[ReSpecQualityFailure, ...]
    semantic_failures: tuple[ReSpecQualityFailure, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.coverage_pct >= self.coverage_threshold
            and not self.domain_failures
            and not self.semantic_failures
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "quality_contract_version": QUALITY_CONTRACT_VERSION,
            "source_id": self.source_id,
            "eligible_file_count": self.eligible_file_count,
            "covered_file_count": self.covered_file_count,
            "coverage_pct": self.coverage_pct,
            "coverage_threshold": self.coverage_threshold,
            "orphan_paths": list(self.orphan_paths),
            "domain_failures": [
                {**asdict(failure), "spec_path": str(failure.spec_path)}
                for failure in self.domain_failures
            ],
            "semantic_failures": [
                {**asdict(failure), "spec_path": str(failure.spec_path)}
                for failure in self.semantic_failures
            ],
            "passed": self.passed,
        }


def validate_semantic_quality_review(
    run_re_dir: Path,
    plan: ReExecutionPlan,
    payload: object,
    expected_domains: set[tuple[str, str]] | None = None,
) -> tuple[ReQualityReport | None, str | None]:
    """Validate the validator's complete, source-evidenced domain audit.

    The review is advisory only when it says PASS, but its coverage is not: the
    agent must account for every refreshed domain. REPAIR findings are converted
    into controller-owned, target-scoped repair work.
    """
    if not isinstance(payload, dict):
        return None, "semantic quality review must be an object"
    if payload.get("schema_version") != SEMANTIC_QUALITY_REVIEW_VERSION:
        return None, "unsupported semantic quality review schema"
    raw_domains = payload.get("domains")
    if not isinstance(raw_domains, list):
        return None, "semantic quality review domains must be a list"

    expected: dict[tuple[str, str], tuple[RePlanSource, ReDomain]] = {}
    try:
        for source in plan.refresh_sources:
            manifest = load_domain_manifest(domain_manifest_path(run_re_dir, source.id))
            if manifest.source_id != source.id or manifest.source_path != source.path:
                return None, "semantic quality review source manifest mismatch"
            for domain in manifest.domains:
                expected[(source.id, domain.domain_id)] = (source, domain)
    except ValueError as exc:
        return None, f"semantic quality review manifest invalid: {exc}"
    if expected_domains is not None:
        if not expected_domains or not expected_domains.issubset(expected):
            return None, "semantic quality review requested domain inventory is invalid"
        expected = {key: expected[key] for key in expected_domains}

    seen: set[tuple[str, str]] = set()
    failures: list[ReSpecQualityFailure] = []
    for item in raw_domains:
        if not isinstance(item, dict):
            return None, "semantic quality review domain must be an object"
        source_id = item.get("source_id")
        domain_id = item.get("domain_id")
        verdict = item.get("verdict")
        findings = item.get("findings")
        evidence = item.get("source_evidence")
        key = (source_id, domain_id)
        if (
            not isinstance(source_id, str)
            or not isinstance(domain_id, str)
            or key not in expected
            or key in seen
        ):
            return None, "semantic quality review domain inventory is invalid"
        if verdict not in {"PASS", "REPAIR"}:
            return None, "semantic quality review verdict must be PASS or REPAIR"
        if not isinstance(findings, list) or any(
            not isinstance(finding, str) or not finding.strip() for finding in findings
        ):
            return None, "semantic quality review findings must be non-empty strings"
        if not isinstance(evidence, list) or any(
            not isinstance(reference, str) for reference in evidence
        ):
            return None, "semantic quality review source_evidence must be strings"
        if verdict == "PASS" and findings:
            return None, "semantic quality review PASS cannot contain findings"
        if verdict == "REPAIR" and not findings:
            return None, "semantic quality review REPAIR requires findings"
        source, domain = expected[key]
        evidence_text = "\n".join(evidence)
        valid_evidence, invalid_evidence = _validated_source_evidence(
            evidence_text,
            source_root=Path(source.absolute_path),
            domain_root=domain.root,
        )
        unmatched_evidence = tuple(
            reference for reference in evidence if not contains_source_reference(reference)
        )
        invalid_source_evidence = tuple(sorted(invalid_evidence)) + unmatched_evidence
        if verdict == "REPAIR" and (
            invalid_source_evidence or len(valid_evidence) < len(findings)
        ):
            return None, _semantic_review_evidence_error(
                source_id=source_id,
                domain_id=domain_id,
                valid_count=len(valid_evidence),
                required_count=len(findings),
                invalid_evidence=invalid_source_evidence,
            )
        if invalid_source_evidence:
            return None, _semantic_review_evidence_error(
                source_id=source_id,
                domain_id=domain_id,
                valid_count=len(valid_evidence),
                required_count=0,
                invalid_evidence=invalid_source_evidence,
            )
        seen.add(key)
        if verdict == "REPAIR":
            records = tuple(
                ReSemanticFindingRecord(
                    finding_id=stable_finding_id(
                        classify_semantic_finding(finding),
                        finding,
                        (evidence[index],),
                    ),
                    category=classify_semantic_finding(finding),
                    text=finding,
                    source_evidence=(evidence[index],),
                )
                for index, finding in enumerate(findings)
            )
            failures.append(
                ReSpecQualityFailure(
                    source_id=source_id,
                    spec_path=(
                        run_re_dir
                        / "sources"
                        / source_id
                        / "specs"
                        / domain_id
                        / "spec.md"
                    ),
                    missing_sections=(),
                    source_evidence_count=len(valid_evidence),
                    domain_id=domain_id,
                    reason="semantic_quality_incomplete",
                    semantic_findings=tuple(findings),
                    semantic_finding_records=records,
                )
            )
    if seen != set(expected):
        missing = sorted(set(expected) - seen)
        extra = sorted(seen - set(expected))
        parts = ["semantic quality review did not audit every refreshed domain"]
        if missing:
            preview = ", ".join(f"{source}/{domain}" for source, domain in missing[:10])
            if len(missing) > 10:
                preview += f", ... +{len(missing) - 10} more"
            parts.append(f"missing {len(missing)}: {preview}")
        if extra:
            preview = ", ".join(f"{source}/{domain}" for source, domain in extra[:10])
            if len(extra) > 10:
                preview += f", ... +{len(extra) - 10} more"
            parts.append(f"unexpected {len(extra)}: {preview}")
        return None, "; ".join(parts)
    return ReQualityReport(passed=not failures, failures=tuple(failures)), None


def _semantic_review_evidence_error(
    *,
    source_id: str,
    domain_id: str,
    valid_count: int,
    required_count: int,
    invalid_evidence: tuple[str, ...],
) -> str:
    parts = [
        f"semantic quality review invalid for {source_id}/{domain_id}:",
    ]
    if required_count:
        parts.append(
            f"REPAIR needs {required_count} valid source citation(s), "
            f"found {valid_count}"
        )
    else:
        parts.append("source_evidence contains invalid source citation(s)")
    if invalid_evidence:
        preview = ", ".join(invalid_evidence[:5])
        if len(invalid_evidence) > 5:
            preview += f", ... +{len(invalid_evidence) - 5} more"
        parts.append(f"invalid source_evidence: {preview}")
    return " ".join(parts)


def validate_staged_re_quality(
    run_re_dir: Path,
    plan: ReExecutionPlan,
) -> ReQualityReport:
    """Validate deep-spec content for every refresh source in a staged run."""
    if plan.profile.depth not in {"logic", "full"}:
        return ReQualityReport(passed=True, failures=())

    failures: list[ReSpecQualityFailure] = []
    for source in plan.refresh_sources:
        specs_root = run_re_dir / "sources" / source.id / "specs"
        manifest_path = domain_manifest_path(run_re_dir, source.id)
        try:
            manifest = load_domain_manifest(manifest_path)
        except ValueError:
            failures.append(
                ReSpecQualityFailure(
                    source_id=source.id,
                    spec_path=manifest_path,
                    missing_sections=(),
                    source_evidence_count=0,
                    reason="domain_manifest_missing_or_invalid",
                )
            )
            continue
        if manifest.source_id != source.id or manifest.source_path != source.path:
            failures.append(
                ReSpecQualityFailure(
                    source_id=source.id,
                    spec_path=manifest_path,
                    missing_sections=(),
                    source_evidence_count=0,
                    reason="domain_manifest_source_mismatch",
                )
            )
            continue

        expected_ids = {domain.domain_id for domain in manifest.domains}
        actual_ids = {
            path.parent.name for path in specs_root.glob("*/spec.md")
        } if specs_root.is_dir() else set()
        for domain in manifest.domains:
            failure = _domain_quality_failure(run_re_dir, source, domain)
            if failure is not None:
                failures.append(failure)
        for unexpected_domain_id in sorted(actual_ids - expected_ids):
            failures.append(
                ReSpecQualityFailure(
                    source_id=source.id,
                    spec_path=specs_root / unexpected_domain_id / "spec.md",
                    missing_sections=(),
                    source_evidence_count=0,
                    domain_id=unexpected_domain_id,
                    reason="unexpected_domain_spec",
                )
            )
    return ReQualityReport(passed=not failures, failures=tuple(failures))


def validate_staged_re_domain_quality(
    run_re_dir: Path,
    plan: ReExecutionPlan,
    source_id: str,
    domain_id: str,
) -> ReQualityReport:
    """Validate one controller-owned domain before accepting its spec dispatch."""
    if plan.profile.depth not in {"logic", "full"}:
        return ReQualityReport(passed=True, failures=())
    source = next((item for item in plan.refresh_sources if item.id == source_id), None)
    if source is None:
        return ReQualityReport(
            passed=False,
            failures=(
                ReSpecQualityFailure(
                    source_id=source_id,
                    spec_path=run_re_dir / "sources" / source_id / "domain-manifest.json",
                    missing_sections=(),
                    source_evidence_count=0,
                    domain_id=domain_id,
                    reason="controller_target_source_not_refreshable",
                ),
            ),
        )
    manifest_path = domain_manifest_path(run_re_dir, source.id)
    try:
        manifest = load_domain_manifest(manifest_path)
    except ValueError:
        return ReQualityReport(
            passed=False,
            failures=(
                ReSpecQualityFailure(
                    source_id=source.id,
                    spec_path=manifest_path,
                    missing_sections=(),
                    source_evidence_count=0,
                    domain_id=domain_id,
                    reason="domain_manifest_missing_or_invalid",
                ),
            ),
        )
    if manifest.source_id != source.id or manifest.source_path != source.path:
        return ReQualityReport(
            passed=False,
            failures=(
                ReSpecQualityFailure(
                    source_id=source.id,
                    spec_path=manifest_path,
                    missing_sections=(),
                    source_evidence_count=0,
                    domain_id=domain_id,
                    reason="domain_manifest_source_mismatch",
                ),
            ),
        )
    domain = next((item for item in manifest.domains if item.domain_id == domain_id), None)
    if domain is None:
        return ReQualityReport(
            passed=False,
            failures=(
                ReSpecQualityFailure(
                    source_id=source.id,
                    spec_path=manifest_path,
                    missing_sections=(),
                    source_evidence_count=0,
                    domain_id=domain_id,
                    reason="controller_target_domain_missing",
                ),
            ),
        )
    failure = _domain_quality_failure(run_re_dir, source, domain)
    return ReQualityReport(passed=failure is None, failures=() if failure is None else (failure,))


def measure_source_quality(
    run_re_dir: Path,
    plan: ReExecutionPlan,
    source_id: str,
    *,
    coverage_threshold: int = 99,
    semantic_failures: tuple[ReSpecQualityFailure, ...] = (),
) -> ReSourceQualityReport:
    """Measure one source from its visible file inventory and valid citations.

    This is intentionally controller-owned: no agent-provided percentage is
    accepted as an input to convergence routing.
    """
    if not 0 <= coverage_threshold <= 100:
        raise ValueError("coverage_threshold must be between 0 and 100")
    source = next((item for item in plan.refresh_sources if item.id == source_id), None)
    if source is None:
        raise ValueError(f"source is not refreshable: {source_id}")
    manifest = load_domain_manifest(domain_manifest_path(run_re_dir, source_id))
    if manifest.source_id != source.id or manifest.source_path != source.path:
        raise ValueError(f"domain manifest source mismatch: {source_id}")

    root = Path(source.absolute_path).resolve()
    eligible = {
        path.relative_to(root).as_posix()
        for path in source_files(root)
    }
    covered: set[str] = set()
    domain_owned: set[str] = set()
    failures: list[ReSpecQualityFailure] = []
    for domain in manifest.domains:
        domain_owned.update(
            path.relative_to(root).as_posix()
            for path in source_files(root if domain.root == "." else root / domain.root)
        )
        failure = _domain_quality_failure(run_re_dir, source, domain)
        if failure is not None:
            failures.append(failure)
        spec_path = run_re_dir / "sources" / source.id / "specs" / domain.domain_id / "spec.md"
        if not spec_path.is_file():
            continue
        for path in _covered_source_paths(
            spec_path.read_text(encoding="utf-8"),
            source_root=root,
            domain_root=domain.root,
        ):
            relative = path.relative_to(root).as_posix()
            if relative in eligible:
                covered.add(relative)

    support_path = run_re_dir / "sources" / source.id / "supporting-artifacts.md"
    if support_path.is_file():
        for path in _covered_source_paths_in_source(
            support_path.read_text(encoding="utf-8"), source_root=root
        ):
            relative = path.relative_to(root).as_posix()
            if relative in eligible and relative not in domain_owned:
                covered.add(relative)

    covered &= eligible
    count = len(eligible)
    coverage = 100.0 if count == 0 else (len(covered) / count) * 100
    return ReSourceQualityReport(
        source_id=source.id,
        eligible_file_count=count,
        covered_file_count=len(covered),
        coverage_pct=coverage,
        coverage_threshold=coverage_threshold,
        orphan_paths=tuple(sorted(eligible - covered)),
        domain_failures=tuple(failures),
        semantic_failures=semantic_failures,
    )


def _domain_quality_failure(
    run_re_dir: Path, source: RePlanSource, domain: ReDomain
) -> ReSpecQualityFailure | None:
    spec_path = run_re_dir / "sources" / source.id / "specs" / domain.domain_id / "spec.md"
    if not spec_path.is_file():
        return ReSpecQualityFailure(
            source_id=source.id,
            spec_path=spec_path,
            missing_sections=DEEP_SPEC_SECTIONS,
            source_evidence_count=0,
            domain_id=domain.domain_id,
            reason="required_domain_spec_missing",
        )
    text = spec_path.read_text(encoding="utf-8")
    missing_sections = tuple(section for section in DEEP_SPEC_SECTIONS if section not in text)
    evidence, invalid_evidence = _validated_source_evidence(
        text,
        source_root=Path(source.absolute_path),
        domain_root=domain.root,
    )
    target = quality_target_for_domain(domain)
    scenario_items = _section_items(
        text, "User Scenarios & Testing", _SCENARIO_HEADING
    )
    functional_requirement_items = _section_items(
        text, "Requirements (Functional)", _FUNCTIONAL_REQUIREMENT_HEADING
    )
    non_functional_requirement_items = _section_items(
        text, "Requirements (Non-Functional)", _NON_FUNCTIONAL_REQUIREMENT_HEADING
    )
    scenarios_without_acceptance = tuple(
        title
        for title, body in scenario_items
        if not _has_acceptance_scenario(body)
    )
    scenarios_without_evidence = _items_without_valid_evidence(
        scenario_items, source_root=Path(source.absolute_path), domain_root=domain.root
    )
    functional_requirements_without_evidence = _items_without_valid_evidence(
        functional_requirement_items,
        source_root=Path(source.absolute_path),
        domain_root=domain.root,
    )
    non_functional_requirements_without_evidence = _items_without_valid_evidence(
        non_functional_requirement_items,
        source_root=Path(source.absolute_path),
        domain_root=domain.root,
    )
    semantic_preflight_findings = check_semantic_preflight(
        spec_path,
        run_re_dir / "sources" / source.id / "analysis.json",
    )
    if not (
        missing_sections
        or len(evidence) < MINIMUM_SOURCE_EVIDENCE
        or invalid_evidence
        or len(scenario_items) < target.minimum_scenarios
        or scenarios_without_acceptance
        or scenarios_without_evidence
        or len(functional_requirement_items) < target.minimum_functional_requirements
        or functional_requirements_without_evidence
        or (
            len(non_functional_requirement_items)
            < target.minimum_non_functional_requirements
        )
        or non_functional_requirements_without_evidence
        or semantic_preflight_findings
    ):
        return None
    return ReSpecQualityFailure(
        source_id=source.id,
        spec_path=spec_path,
        missing_sections=missing_sections,
        source_evidence_count=len(evidence),
        domain_id=domain.domain_id,
        invalid_source_evidence=tuple(sorted(invalid_evidence)),
        expected_scenario_count=target.minimum_scenarios,
        scenario_count=len(scenario_items),
        scenarios_without_acceptance=scenarios_without_acceptance,
        scenarios_without_evidence=scenarios_without_evidence,
        expected_functional_requirement_count=target.minimum_functional_requirements,
        functional_requirement_count=len(functional_requirement_items),
        functional_requirements_without_evidence=functional_requirements_without_evidence,
        expected_non_functional_requirement_count=(
            target.minimum_non_functional_requirements
        ),
        non_functional_requirement_count=len(non_functional_requirement_items),
        non_functional_requirements_without_evidence=(
            non_functional_requirements_without_evidence
        ),
        semantic_preflight_findings=semantic_preflight_findings,
    )


@dataclass(frozen=True)
class ReDomainQualityTarget:
    """Adaptive deep-spec minima derived from the owned source domain size."""

    complexity_units: int
    minimum_scenarios: int
    minimum_functional_requirements: int
    minimum_non_functional_requirements: int


def quality_target_for_domain(domain: ReDomain) -> ReDomainQualityTarget:
    """Set deep-spec expectations from domain scale without accepting summaries."""
    units = max(
        1,
        _ceil_div(domain.source_file_count, _FILES_PER_COMPLEXITY_UNIT),
        _ceil_div(domain.source_line_count, _LINES_PER_COMPLEXITY_UNIT),
    )
    return ReDomainQualityTarget(
        complexity_units=units,
        minimum_scenarios=min(_MAX_SCENARIOS, 4 + units),
        minimum_functional_requirements=min(
            _MAX_FUNCTIONAL_REQUIREMENTS, 5 + (2 * units)
        ),
        minimum_non_functional_requirements=min(
            _MAX_NON_FUNCTIONAL_REQUIREMENTS, 2 + ((units + 1) // 2)
        ),
    )


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def _section_items(
    text: str, section: str, heading_pattern: re.Pattern[str]
) -> tuple[tuple[str, str], ...]:
    """Return matching level-three items inside one exact level-two section."""
    section_text = _section_text(text, section)
    if section_text is None:
        return ()
    headings = list(_SUBSECTION_HEADING.finditer(section_text))
    items: list[tuple[str, str]] = []
    for index, match in enumerate(headings):
        title = match.group("title").strip()
        if not heading_pattern.match(title):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(section_text)
        items.append((title, section_text[match.end() : end]))
    return tuple(items)


def _section_text(text: str, section: str) -> str | None:
    headings = list(_SECTION_HEADING.finditer(text))
    for index, match in enumerate(headings):
        if match.group("title").strip() != section:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        return text[match.end() : end]
    return None


def _has_acceptance_scenario(text: str) -> bool:
    return bool(
        re.search(r"\bGiven\b[\s\S]*?\bWhen\b[\s\S]*?\bThen\b", text, re.IGNORECASE)
    )


def _items_without_valid_evidence(
    items: tuple[tuple[str, str], ...], *, source_root: Path, domain_root: str
) -> tuple[str, ...]:
    missing: list[str] = []
    for title, body in items:
        valid, _invalid = _validated_source_evidence(
            body, source_root=source_root, domain_root=domain_root
        )
        if not valid:
            missing.append(title)
    return tuple(missing)


def _validated_source_evidence(
    text: str,
    *,
    source_root: Path,
    domain_root: str,
) -> tuple[set[str], set[str]]:
    """Return valid and invalid source-relative path-and-line references."""
    valid: set[str] = set()
    invalid: set[str] = set()
    root = source_root.resolve()
    for match in source_reference_matches(text):
        raw_path = match.group("path").strip()
        ranges = source_reference_ranges(match)
        reference = match.group(0)
        relative = Path(raw_path)
        if (
            not raw_path
            or relative.is_absolute()
            or ".." in relative.parts
            or any(end < start for start, end in ranges)
        ):
            invalid.add(reference)
            continue
        candidate = _resolve_domain_evidence_path(
            relative, source_root=root, domain_root=domain_root
        )
        if candidate is None or any(
            end > _line_count(candidate) for _start, end in ranges
        ):
            invalid.add(reference)
            continue
        valid.add(reference)
    return valid, invalid


def _covered_source_paths(
    text: str, *, source_root: Path, domain_root: str
) -> set[Path]:
    """Resolve only valid, in-domain evidence references to source files."""
    covered: set[Path] = set()
    for match in source_reference_matches(text):
        raw_path = match.group("path").strip()
        ranges = source_reference_ranges(match)
        relative = Path(raw_path)
        if (
            not raw_path
            or relative.is_absolute()
            or ".." in relative.parts
            or any(end < start for start, end in ranges)
        ):
            continue
        candidate = _resolve_domain_evidence_path(
            relative, source_root=source_root, domain_root=domain_root
        )
        if candidate is not None and all(
            end <= _line_count(candidate) for _start, end in ranges
        ):
            covered.add(candidate)
    return covered


def _covered_source_paths_in_source(text: str, *, source_root: Path) -> set[Path]:
    """Resolve valid source-root evidence for supporting artifacts only."""
    covered: set[Path] = set()
    for match in source_reference_matches(text):
        raw_path = match.group("path").strip()
        ranges = source_reference_ranges(match)
        relative = Path(raw_path)
        if (
            not raw_path
            or relative.is_absolute()
            or ".." in relative.parts
            or any(end < start for start, end in ranges)
        ):
            continue
        candidate = (source_root / relative).resolve()
        try:
            candidate.relative_to(source_root)
        except ValueError:
            continue
        if candidate.is_file() and all(
            end <= _line_count(candidate) for _start, end in ranges
        ):
            covered.add(candidate)
    return covered


def _resolve_domain_evidence_path(
    relative: Path, *, source_root: Path, domain_root: str
) -> Path | None:
    """Resolve source-root or domain-root evidence without crossing domain scope."""
    domain_path = (source_root / domain_root).resolve()
    candidates = ((source_root / relative).resolve(), (domain_path / relative).resolve())
    for candidate in candidates:
        try:
            candidate.relative_to(domain_path)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def write_re_quality_report(run_re_dir: Path, report: ReQualityReport) -> Path:
    """Atomically persist the deterministic gate report for diagnostics/repair."""
    path = run_re_dir / "quality" / "deep-spec-gate.json"
    return _write_quality_report(path, report)


def write_re_semantic_quality_report(run_re_dir: Path, report: ReQualityReport) -> Path:
    """Persist the complete semantic audit used to schedule target repairs."""
    path = run_re_dir / "quality" / "semantic-quality-review.json"
    return _write_quality_report(path, report)


def write_re_target_quality_report(
    run_re_dir: Path,
    source_id: str,
    domain_id: str,
    report: ReQualityReport,
) -> Path:
    """Persist the exact gate failure that a source-domain repair must address."""
    path = run_re_dir / "quality" / "targets" / source_id / f"{domain_id}.json"
    return _write_quality_report(path, report)


def write_re_source_quality_report(
    run_re_dir: Path, report: ReSourceQualityReport
) -> Path:
    """Persist one deterministic source-local convergence measurement."""
    path = run_re_dir / "quality" / "sources" / f"{report.source_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report.to_json_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def _write_quality_report(path: Path, report: ReQualityReport) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report.to_json_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path
