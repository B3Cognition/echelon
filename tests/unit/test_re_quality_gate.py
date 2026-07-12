from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_planner import ReExecutionPlan
from harness.re_quality_gate import validate_staged_re_quality
from tests.unit.test_re_publication import write_valid_re_run


def _plan(run_dir: Path) -> ReExecutionPlan:
    return ReExecutionPlan.from_json_dict(
        __import__("json").loads(
            (run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8")
        )
    )


@pytest.mark.unit
def test_shallow_architecture_summary_reports_all_missing_deep_requirements(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text(
        "# Build Configuration\n\n"
        "## Purpose and Responsibility\n\n"
        "The build system produces the frontend bundle.\n\n"
        "## Architecture\n\n"
        "Webpack assembles the modules.\n\n"
        "## Key Files and Entry Points\n\n"
        "The configuration is in the build directory.\n",
        encoding="utf-8",
    )

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert not report.passed
    assert len(report.failures) == 1
    failure = report.failures[0]
    assert failure.source_id == "api"
    assert failure.spec_path == spec
    assert failure.missing_sections == (
        "User Scenarios & Testing",
        "Requirements (Functional)",
        "Key Entities",
        "Edge Cases",
    )
    assert failure.source_evidence_count == 0
