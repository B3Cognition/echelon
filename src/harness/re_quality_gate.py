"""Deterministic deep-spec quality validation for staged RE output."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.re_domain_manifest import domain_manifest_path, load_domain_manifest
from harness.re_planner import ReExecutionPlan


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
            spec_path = specs_root / domain.domain_id / "spec.md"
            if not spec_path.is_file():
                failures.append(
                    ReSpecQualityFailure(
                        source_id=source.id,
                        spec_path=spec_path,
                        missing_sections=DEEP_SPEC_SECTIONS,
                        source_evidence_count=0,
                        domain_id=domain.domain_id,
                        reason="required_domain_spec_missing",
                    )
                )
                continue
            text = spec_path.read_text(encoding="utf-8")
            missing_sections = tuple(
                section for section in DEEP_SPEC_SECTIONS if section not in text
            )
            evidence, invalid_evidence = _validated_source_evidence(
                text,
                source_root=Path(source.absolute_path),
                domain_root=domain.root,
            )
            if (
                missing_sections
                or len(evidence) < MINIMUM_SOURCE_EVIDENCE
                or invalid_evidence
            ):
                failures.append(
                    ReSpecQualityFailure(
                        source_id=source.id,
                        spec_path=spec_path,
                        missing_sections=missing_sections,
                        source_evidence_count=len(evidence),
                        domain_id=domain.domain_id,
                        invalid_source_evidence=tuple(sorted(invalid_evidence)),
                    )
                )
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
            or not _is_within_domain(raw_path, domain_root)
        ):
            invalid.add(reference)
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            invalid.add(reference)
            continue
        if not candidate.is_file() or end > _line_count(candidate):
            invalid.add(reference)
            continue
        valid.add(reference)
    return valid, invalid


def _is_within_domain(path: str, domain_root: str) -> bool:
    return domain_root == "." or path == domain_root or path.startswith(domain_root + "/")


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def write_re_quality_report(run_re_dir: Path, report: ReQualityReport) -> Path:
    """Atomically persist the deterministic gate report for diagnostics/repair."""
    path = run_re_dir / "quality" / "deep-spec-gate.json"
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
