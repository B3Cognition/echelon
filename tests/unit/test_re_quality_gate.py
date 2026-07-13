from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_domain_manifest import domain_manifest_path
from harness.re_planner import ReExecutionPlan
from harness.re_quality_gate import (
    validate_staged_re_domain_quality,
    validate_staged_re_quality,
)
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


@pytest.mark.unit
def test_gate_rejects_a_source_when_any_manifest_domain_has_no_spec(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    manifest_path = domain_manifest_path(run_dir / "re", "api")
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    manifest["domains"].append(
        {
            "domain_id": "002-re-worker",
            "root": "worker",
            "source_file_count": 1,
            "source_line_count": 1,
        }
    )
    manifest_path.write_text(__import__("json").dumps(manifest), encoding="utf-8")

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert not report.passed
    assert len(report.failures) == 1
    assert report.failures[0].domain_id == "002-re-worker"
    assert report.failures[0].reason == "required_domain_spec_missing"


@pytest.mark.unit
def test_gate_rejects_source_evidence_outside_the_domain_root(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("src/file-1.ts:1", "outside.ts:1"),
        encoding="utf-8",
    )

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert not report.passed
    assert report.failures[0].invalid_source_evidence == ("`outside.ts:1`",)


@pytest.mark.unit
def test_gate_accepts_domain_relative_source_evidence(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("src/file-", "file-"),
        encoding="utf-8",
    )

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert report.passed


@pytest.mark.unit
def test_target_gate_reports_only_its_declared_domain(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    report = validate_staged_re_domain_quality(
        run_dir / "re", _plan(run_dir), "api", "001-re-domain"
    )

    assert not report.passed
    assert len(report.failures) == 1
    assert report.failures[0].domain_id == "001-re-domain"
    assert report.failures[0].spec_path == spec
