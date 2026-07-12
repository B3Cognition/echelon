"""Deterministic deep-spec quality validation for staged RE output."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.re_planner import ReExecutionPlan


SOURCE_REFERENCE = re.compile(r"`[^`\n]+:\d+(?:-\d+)?`")
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
        specs = sorted(specs_root.glob("*/spec.md"))
        if not specs:
            failures.append(
                ReSpecQualityFailure(
                    source_id=source.id,
                    spec_path=specs_root,
                    missing_sections=DEEP_SPEC_SECTIONS,
                    source_evidence_count=0,
                )
            )
            continue
        for spec_path in specs:
            text = spec_path.read_text(encoding="utf-8")
            missing_sections = tuple(
                section for section in DEEP_SPEC_SECTIONS if section not in text
            )
            evidence_count = len(set(SOURCE_REFERENCE.findall(text)))
            if missing_sections or evidence_count < MINIMUM_SOURCE_EVIDENCE:
                failures.append(
                    ReSpecQualityFailure(
                        source_id=source.id,
                        spec_path=spec_path,
                        missing_sections=missing_sections,
                        source_evidence_count=evidence_count,
                    )
                )
    return ReQualityReport(passed=not failures, failures=tuple(failures))


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
