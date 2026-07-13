"""Deterministic deep-spec quality validation for staged RE output."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.re_domain_manifest import ReDomain, domain_manifest_path, load_domain_manifest
from harness.re_planner import ReExecutionPlan, RePlanSource


SOURCE_REFERENCE = re.compile(
    r"`(?P<path>[^`\n:]+):(?P<start>\d+)(?:-(?P<end>\d+))?`"
)
DEEP_SPEC_SECTIONS = (
    "User Scenarios & Testing",
    "Requirements (Functional)",
    "Key Entities",
    "Edge Cases",
)
MINIMUM_SOURCE_EVIDENCE = 5


@dataclass(frozen=True)
class ReSpecQualityFailure:
    source_id: str
    spec_path: Path
    missing_sections: tuple[str, ...]
    source_evidence_count: int
    domain_id: str | None = None
    reason: str = "deep_spec_incomplete"
    invalid_source_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReQualityReport:
    passed: bool
    failures: tuple[ReSpecQualityFailure, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "passed": self.passed,
            "failures": [
                {
                    **asdict(failure),
                    "spec_path": str(failure.spec_path),
                }
                for failure in self.failures
            ],
        }


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
    if not (
        missing_sections
        or len(evidence) < MINIMUM_SOURCE_EVIDENCE
        or invalid_evidence
    ):
        return None
    return ReSpecQualityFailure(
        source_id=source.id,
        spec_path=spec_path,
        missing_sections=missing_sections,
        source_evidence_count=len(evidence),
        domain_id=domain.domain_id,
        invalid_source_evidence=tuple(sorted(invalid_evidence)),
    )


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
    for match in SOURCE_REFERENCE.finditer(text):
        raw_path = match.group("path").strip()
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        reference = match.group(0)
        relative = Path(raw_path)
        if (
            not raw_path
            or relative.is_absolute()
            or ".." in relative.parts
            or end < start
        ):
            invalid.add(reference)
            continue
        candidate = _resolve_domain_evidence_path(
            relative, source_root=root, domain_root=domain_root
        )
        if candidate is None or end > _line_count(candidate):
            invalid.add(reference)
            continue
        valid.add(reference)
    return valid, invalid


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


def write_re_target_quality_report(
    run_re_dir: Path,
    source_id: str,
    domain_id: str,
    report: ReQualityReport,
) -> Path:
    """Persist the exact gate failure that a source-domain repair must address."""
    path = run_re_dir / "quality" / "targets" / source_id / f"{domain_id}.json"
    return _write_quality_report(path, report)


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
